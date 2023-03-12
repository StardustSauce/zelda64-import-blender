# zelda64-import-blender
# Import models from Zelda64 files into Blender
# Copyright (C) 2013 SoulofDeity
# Copyright (C) 2020 Dragorn421
# Copyright (C) 2023 StardustSauce
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>

bl_info = {
    "name":        "Zelda64 Importer",
    "description": "Import Zelda64 for Blender 2.8+",
    "version":     (3, 0),
    "author":      "SoulofDeity",
    "blender":     (2, 80, 0),
    "location":    "File > Import-Export",
    "warning":     "",
    "wiki_url":    "https://github.com/StardustSauce/zelda64-import-blender",
    "tracker_url": "https://github.com/StardustSauce/zelda64-import-blender",
    "support":     "COMMUNITY",
    "category":    "Import-Export"
}

"""Anim stuff: RodLima http://www.facebook.com/rod.lima.96?ref=tn_tnmn"""


if "bpy" in locals():
    import importlib
    importlib.reload(log)
else:
    from .log import (
        logging_trace_level,
        logging,
        registerLogging,
        unregisterLogging,
        setLoggingLevel,
        getLogger,
        setLogFile,
        setLogOperator
    )
    from .io_import_z64 import (
        F3DZEX
    )

import os
import time

import bpy
from bpy.props import *
from bpy_extras.io_utils import ExportHelper, ImportHelper

class ImportZ64(bpy.types.Operator, ImportHelper):
    """Load a Zelda64 File"""
    bl_idname    = "import_scene.zobj"
    bl_label     = "Import Zelda64"
    bl_options   = {"PRESET", "UNDO"}
    filename_ext = ".zobj"
    filter_glob: StringProperty(default="*.zobj;*.zroom;*.zmap", options={"HIDDEN"})

    files: CollectionProperty(
        name="Files",
        type=bpy.types.OperatorFileListElement,)
    directory: StringProperty(subtype="DIR_PATH")

    load_other_segments: BoolProperty(name="Load Data From Other Segments",
                                    description="Load data from other segments",
                                    default=True,)
    import_type: EnumProperty(
        name="Import type",
        items=(("AUTO", "Auto", "Assume Room File if .zroom or .zmap, otherwise assume Object File"),
               ("OBJECT", "Object File", "Assume the file being imported is an object file"),
               ("ROOM", "Room File", "Assume the file being imported is a room file"),),
        description="What to assume the file being imported is",
        default="AUTO",)
    import_strategy: EnumProperty(name="Detect DLists",
                                 items=(("NO_DETECTION", "Minimum", "Maps: only use headers\nObjects: only use hierarchies\nOnly this option will not create unexpected geometry"),
                                        ("BRUTEFORCE", "Bruteforce", "Try to import everything that looks like a display list\n(ignores header for maps)"),
                                        ("SMART", "Smart-ish", "Minimum + Bruteforce but avoids reading the same display lists several times"),
                                        ("TRY_EVERYTHING", "Try everything", "Minimum + Bruteforce"),),
                                 description="How to find display lists to import (try this if there is missing geometry)",
                                 default="NO_DETECTION",)
    vertex_mode: EnumProperty(name="Vtx Mode",
                             items=(("COLORS", "COLORS", "Use vertex colors"),
                                    ("NORMALS", "NORMALS", "Use vertex normals as shading"),
                                    ("NONE", "NONE", "Don't use vertex colors or normals"),
                                    ("AUTO", "AUTO", "Switch between normals and vertex colors automatically according to 0xD9 G_GEOMETRYMODE flags"),),
                             description="Legacy option, shouldn't be useful",
                             default="AUTO",)
    enable_matrices: BoolProperty(name="Matrices",
                                 description="Use 0xDA G_MTX and 0xD8 G_POPMTX commands",
                                 default=True,)
    detected_display_lists_use_transparency: BoolProperty(name="Default to transparency",
                                                         description="Set material to use transparency or not for display lists that were detected",
                                                         default=False,)
    detected_display_lists_consider_unimplemented_invalid: BoolProperty(
                                    name="Unimplemented => Invalid",
                                    description="Consider that unimplemented opcodes are invalid when detecting display lists.\n"
                                                "The reasoning is that unimplemented opcodes are very rare or never actually used.",
                                    default=True,)
    enable_prim_color: BoolProperty(name="Use Prim Color",
                                  description="Enable blending with primitive color",
                                  default=False,) # this may be nice for strictly importing but exporting again will then not be exact
    enable_env_color: BoolProperty(name="Use Env Color",
                                 description="Enable blending with environment color",
                                 default=False,) # same as primColor above
    invert_env_color: BoolProperty(name="Invert Env Color",
                                 description="Invert environment color (temporary fix)",
                                 default=False,) # TODO: what is this?
    export_textures: BoolProperty(name="Export Textures",
                                 description="Export textures for the model",
                                 default=True,)
    import_textures: BoolProperty(name="Import Textures",
                                 description="Import textures for the model",
                                 default=True,)
    enable_tex_clamp_blender: BoolProperty(name="Texture Clamp",
                                 description="Enable texture clamping in Blender, used by Blender in the 3d viewport and by zzconvert",
                                 default=False,) # TODO: This varies per material. There must be a way generate this information.
    replicate_tex_mirror_blender: BoolProperty(name="Texture Mirror",
                                  description="Replicate texture mirroring by writing the textures with the mirrored parts (with double width/height) instead of the initial texture",
                                  default=False,)
    enable_tex_clamp_sharp_ocarina_tags: BoolProperty(name="Texture Clamp SO Tags",
                                 description="Add #ClampX and #ClampY tags where necessary in the texture filename, used by SharpOcarina",
                                 default=False,)
    enable_tex_mirror_sharp_ocarina_tags: BoolProperty(name="Texture Mirror SO Tags",
                                  description="Add #MirrorX and #MirrorY tags where necessary in the texture filename, used by SharpOcarina",
                                  default=False,)
    # Shadeless materials no longer exist in 2.80. Only Eevee Renderer has an alternative.
    # enable_shadeless_materials: BoolProperty(name="Shadeless Materials",
    #                               description="Set materials to be shadeless, prevents using environment colors in-game",
    #                               default=False,)
    original_object_scale: IntProperty(name="File Scale", # TODO: Ground this in a Unit system
                             description="Scale of imported object, blender model will be scaled 1/(file scale) (use 1 for maps, actors are usually 100, 10 or 1) (0 defaults to 1 for maps and 100 for actors)",
                             default=0, min=0, soft_max=1000)
    load_animations: BoolProperty(name="Load animations",
                             description="For animated actors, load all animations or none",
                             default=True,)
    majora_anims: BoolProperty(name="MajorasAnims",
                             description="Majora's Mask Link's Anims.",
                             default=False,)
    external_animes: BoolProperty(name="ExternalAnimes",
                             description="Load External Animes.",
                             default=False,)
    prefix_multi_import: BoolProperty(name="Prefix multi-import",
                             description="Add a prefix to imported data (objects, materials, images...) when importing several files at once",
                             default=True,)
    set_view_3d_parameters: BoolProperty(name="Set 3D View parameters",
                             description="For maps, use a more appropriate grid size and clip distance",
                             default=True,)
    logging_level: IntProperty(name="Log level",
                             description=f"(logs in the system console) The lower, the more logs. trace={logging_trace_level} debug={logging.DEBUG} info={logging.INFO}",
                             default=logging.INFO, min=1, max=51)
    report_logging_level: IntProperty(name="Report level",
                             description=f"What logs to report to Blender. When the import is done, warnings and errors are shown, if any. trace={logging_trace_level} debug={logging.DEBUG} info={logging.INFO}",
                             default=logging.INFO, min=1, max=51)
    logging_logfile_enable: BoolProperty(name="Log to file",
                             description="Log everything (all levels) to a file",
                             default=False,)
    logging_logfile_path: StringProperty(name="Log file path",
                             #subtype="FILE_PATH", # cannot use two FILE_PATH at the same time
                             description="File to write logs to\nPath can be relative (to imported file) or absolute",
                             default="log_io_import_z64.txt",)

    def execute(self, context):
        keywords = self.as_keywords()

        setLoggingLevel(self.logging_level)
        log = getLogger("ImportZ64.execute")
        if self.logging_logfile_enable:
            logfile_path = self.logging_logfile_path
            if not os.path.isabs(logfile_path):
                logfile_path = os.path.join(self.directory, logfile_path)
            log.info(f"Writing logs to {logfile_path}")
            setLogFile(logfile_path)
        setLogOperator(self, self.report_logging_level)

        try:
            for file in self.files:
                filepath = os.path.join(self.directory, file.name)
                if len(self.files) == 1 or not self.prefix_multi_import:
                    prefix = ""
                else:
                    prefix = file.name + "_"
                self.executeSingle(filepath, keywords, prefix=prefix)
            bpy.context.view_layer.update()
        finally:
            setLogFile(None)
            setLogOperator(None)
        return {"FINISHED"}

    def executeSingle(self, filepath, keywords, prefix=""):
        keywords["fpath"], fext = os.path.splitext(filepath)
        keywords["fpath"], fname = os.path.split(keywords["fpath"])

        if self.import_type == "AUTO":
            if fext.lower() in {".zmap", ".zroom"}:
                importType = "ROOM"
            else:
                importType = "OBJECT"
        else:
            importType = self.import_type

        if self.original_object_scale == 0:
            if importType == "ROOM":
                keywords["scale_factor"] = 1 # maps are actually stored 1:1
            else:
                keywords["scale_factor"] = 1 / 100 # most objects are stored 100:1
        else:
            keywords["scale_factor"] = 1 / self.original_object_scale

        log = getLogger("ImportZ64.executeSingle")

        log.info(f"Importing '{fname}'...")
        time_start = time.time()
        self.run_import(filepath, importType, keywords, prefix=prefix)
        log.info(f"SUCCESS:  Elapsed time {time.time() - time_start:.4f} sec")

    def run_import(self, filepath, importType, keywords, prefix=""):
        fpath, fext = os.path.splitext(filepath)
        fpath, fname = os.path.split(fpath)

        log = getLogger("ImportZ64.run_import")
        f3dzex = F3DZEX(self.detected_display_lists_use_transparency, keywords, prefix=prefix)
        f3dzex.loaddisplaylists(os.path.join(fpath, "displaylists.txt"))
        if self.load_other_segments:
            log.debug("Loading other segments")
            # for segment 2, use [room file prefix]_scene then [same].zscene then segment_02.zdata then fallback to any .zscene
            scene_file = None
            if "_room" in fname:
                scene_file = f"{fpath}/{fname[:fname.index('_room')]}_scene"
                if not os.path.isfile(scene_file):
                    scene_file += ".zscene"
            if not scene_file or not os.path.isfile(scene_file):
                scene_file = fpath + "/segment_02.zdata"
            if not scene_file or not os.path.isfile(scene_file):
                scene_file = None
                for f in os.listdir(fpath):
                    if f.endswith(".zscene"):
                        if scene_file:
                            log.warning(f"Found another .zscene file {f}, keeping {scene_file}")
                        else:
                            scene_file = f"{fpath}/{f}"
            if scene_file and os.path.isfile(scene_file):
                log.info(f"Loading scene segment 0x02 from {scene_file}")
                f3dzex.loadSegment(2, scene_file)
            else:
                log.debug("No file found to load scene segment 0x02 from")
            for i in range(16):
                if i == 2:
                    continue
                # I was told this is "ZRE" naming?
                segment_data_file = f"{fpath}/segment_{i:02X}.zdata"
                if os.path.isfile(segment_data_file):
                    log.info(f"Loading segment 0x{i:02X} from {segment_data_file}")
                    f3dzex.loadSegment(i, segment_data_file)
                else:
                    log.debug(f"No file found to load segment 0x{i:02X} from")

        if importType == "ROOM":
            log.debug("Importing room")
            f3dzex.loadSegment(0x03, filepath)
            f3dzex.importMap()
        else:
            log.debug("Importing object")
            f3dzex.loadSegment(0x06, filepath)
            f3dzex.importObj()

        if self.set_view_3d_parameters:
            for screen in bpy.data.screens:
                for area in screen.areas:
                    if area.type == "VIEW_3D":
                        if importType == "ROOM":
                            area.spaces.active.clip_end = 900000
                        area.spaces.active.shading.type = "MATERIAL"

    def draw(self, context):
        pass

class ZOBJ_PT_import_config(bpy.types.Panel):
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_label = "Config"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_SCENE_OT_zobj"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "import_type", text="Type")
        layout.prop(operator, "import_strategy", text="Strategy")
        if operator.import_strategy != "NO_DETECTION":
            layout.prop(operator, "detected_display_lists_use_transparency")
            layout.prop(operator, "detected_display_lists_consider_unimplemented_invalid")
        layout.prop(operator, "vertex_mode")
        layout.prop(operator, "load_other_segments")
        layout.prop(operator, "original_object_scale")
        layout.prop(operator, "enable_matrices")
        layout.prop(operator, "prefix_multi_import")
        layout.prop(operator, "set_view_3d_parameters")

class ZOBJ_PT_import_texture(bpy.types.Panel):
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_label = "Textures"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_SCENE_OT_zobj"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "enable_tex_clamp_blender")
        layout.prop(operator, "replicate_tex_mirror_blender")
        if operator.replicate_tex_mirror_blender:
            wBox = layout.box()
            wBox.label(text="Enabling texture mirroring", icon="ERROR")
            wBox.label(text="will break exporting with", icon="BLANK1")
            wBox.label(text="SharpOcarina, and may break", icon="BLANK1")
            wBox.label(text="exporting in general with", icon="BLANK1")
            wBox.label(text="other tools.", icon="BLANK1")
        layout.prop(operator, "enable_tex_clamp_sharp_ocarina_tags")
        layout.prop(operator, "enable_tex_mirror_sharp_ocarina_tags")

        layout.separator()

        layout.prop(operator, "enable_prim_color")
        layout.prop(operator, "enable_env_color")
        layout.prop(operator, "invert_env_color")
        layout.prop(operator, "export_textures")
        layout.prop(operator, "import_textures")

class ZOBJ_PT_import_animation(bpy.types.Panel):
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_label = "Animations"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_SCENE_OT_zobj"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "load_animations")
        layout.prop(operator, "majora_anims")
        layout.prop(operator, "external_animes") 

class ZOBJ_PT_import_logging(bpy.types.Panel):
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_label = "Logging"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_SCENE_OT_zobj"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "logging_level")
        layout.prop(operator, "logging_logfile_enable")
        if operator.logging_logfile_enable:
            layout.prop(operator, "logging_logfile_path")

def menu_func_import(self, context):
    self.layout.operator(ImportZ64.bl_idname, text="Zelda64 (.zobj;.zroom;.zmap)")

classes = (
    ImportZ64,
    ZOBJ_PT_import_config,
    ZOBJ_PT_import_texture,
    ZOBJ_PT_import_animation,
    ZOBJ_PT_import_logging
)

def register():
    registerLogging()
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

    for cls in classes:
        bpy.utils.unregister_class(cls)
    unregisterLogging()

if __name__ == "__main__":
    register()
