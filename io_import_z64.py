import bpy, bmesh, os, struct

from bpy.props import *
from bpy_extras.image_utils import load_image
from bpy_extras.node_shader_utils import PrincipledBSDFWrapper
from math import *
from struct import pack, unpack_from

from mathutils import Vector, Euler, Quaternion, Matrix
from .log import *

def splitOffset(offset):
    return offset >> 24, offset & 0x00FFFFFF

def translateRotation(rot):
    """ axis, angle """
    return Matrix.Rotation(rot[3], 4, Vector(rot[:3]))

def validOffset(segment, offset):
    seg, offset = splitOffset(offset)
    if seg > 15:
        return False
    if offset >= len(segment[seg]):
        return False
    return True

class Tile:
    def __init__(self):
        self.current_texture_file_path = None
        self.texFmt, self.texBytes = 0x00, 0
        self.dims = [0, 0]
        self.r_dims = [0, 0]
        self.texSiz = 0
        self.lineSize = 0
        self.rect = Vector([0, 0, 0, 0])
        self.scale = Vector([1, 1])
        self.ratio = Vector([1, 1])
        self.mirror = [False, False]
        self.wrap = [False, False]
        self.mask = Vector([0, 0])
        self.shift = Vector([0, 0])
        self.tshift = Vector([0, 0])
        self.offset = Vector([0, 0])
        self.data = 0x00000000
        self.palette = 0x00000000

    def getFormatName(self):
        formats = {0: "RGBA", 1: "YUV", 2: "CI", 3: "IA", 4: "I"}
        sizes = {0: "4", 1: "8", 2: "16", 3: "32"}
        return f"{formats.get(self.texFmt, 'UnkFmt')}{sizes.get(self.texSiz, '_UnkSiz')}"

    def create(
            self,
            segment, 
            use_transparency, 
            replicate_tex_mirror_blender, 
            enable_mirror_tags,
            enable_clamp_tags, 
            enable_blender_clamp,
            export_textures,
            fpath,
            prefix=""
        ):
        # TODO: texture files are written several times, at each usage
        log = getLogger("Tile.create")
        fmtName = self.getFormatName()
        #Noka here
        suffix = ""
        w = self.r_dims[0]
        if self.mirror[0]:
            if replicate_tex_mirror_blender:
                w <<= 1
            if enable_mirror_tags:
                suffix += "#MirrorX"
        h = self.r_dims[1]
        if self.mirror[1]:
            if replicate_tex_mirror_blender:
                h <<= 1
            if enable_mirror_tags:
                suffix += "#MirrorY"
        if not self.wrap[0] and enable_clamp_tags:
            suffix += "#ClampX"
        if not self.wrap[0] and enable_clamp_tags:
            suffix += "#ClampY"
        self.current_texture_file_path = os.path.join(fpath, "textures", f"{prefix}{fmtName}_{self.data:08X}{f'_pal{self.palette:08X}' if self.texFmt == 2 else ''}{suffix}.tga")
        if export_textures: # FIXME: exportTextures == False breaks the script
            try:
                os.mkdir(os.path.join(fpath, "textures"))
            except FileExistsError:
                pass
            except:
                log.exception(f"Could not create textures directory {os.path.join(fpath, 'textures')}")
                pass
            if not os.path.isfile(self.current_texture_file_path):
                log.debug(f"Writing texture {self.current_texture_file_path} (format 0x{self.texFmt:02X})")
                with open(self.current_texture_file_path, "wb") as file:
                    self.write_error_encountered = False
                    if self.texFmt == 2:
                        if self.texSiz not in (0, 1):
                            log.error(f"Unknown texture format {self.texFmt} with pixel size {self.texSiz}")
                        p = 16 if self.texSiz == 0 else 256
                        file.write(pack("<BBBHHBHHHHBB",
                            0,  # image comment length
                            1,  # 1 = paletted
                            1,  # 1 = indexed uncompressed colors
                            0,  # index of first palette entry (?)
                            p,  # amount of entries in palette
                            32, # bits per pixel
                            0,  # bottom left X (?)
                            0,  # bottom left Y (?)
                            w,  # width
                            h,  # height
                            8,  # pixel depth
                            8   # 8 bits alpha hopefully?
                        ))
                        self.writePalette(file, segment, p)
                    else:
                        file.write(pack("<BBBHHBHHHHBB",
                            0, # image comment length
                            0, # no palette
                            2, # uncompressed Truecolor (24-32 bits)
                            0, # irrelevant, no palette
                            0, # irrelevant, no palette
                            0, # irrelevant, no palette
                            0, # bottom left X (?)
                            0, # bottom left Y (?)
                            w, # width
                            h, # height
                            32,# pixel depth
                            8  # 8 bits alpha (?)
                        ))
                    self.writeImageData(
                        file,
                        segment,
                        replicate_tex_mirror_blender,
                        self.mirror[1] and replicate_tex_mirror_blender
                    )
                if self.write_error_encountered:
                    oldName = self.current_texture_file_path
                    oldNameDir, oldNameBase = os.path.split(oldName)
                    newName = os.path.join(oldNameDir, f"{prefix}fallback_{oldNameBase}")
                    log.warning(f"Moving failed texture file import from {oldName} to {newName}")
                    if os.path.isfile(newName):
                        os.remove(newName)
                    os.rename(oldName, newName)
                    self.current_texture_file_path = newName
        try:
            img = load_image(self.current_texture_file_path)

            mtl_name = f"{prefix}mtl_{self.data:08X}"
            material = bpy.data.materials.new(name=mtl_name)
            material.use_nodes = True

            bsdf = PrincipledBSDFWrapper(material, is_readonly=False)
            bsdf.base_color_texture.image = img

            bsdf_node = bsdf.node_principled_bsdf
            tex_node = bsdf.base_color_texture.node_image

            nodes = material.node_tree.nodes
            links = material.node_tree.links

            if enable_blender_clamp:
                tex_node.extension = "EXTEND"
                coordinate_node = nodes.new(type="ShaderNodeTexCoord")
                separate_node = nodes.new(type="ShaderNodeSeparateXYZ")
                combine_node = nodes.new(type="ShaderNodeCombineXYZ")
                links.new(coordinate_node.outputs["UV"], separate_node.inputs["Vector"])
                links.new(separate_node.outputs["Z"], combine_node.inputs["Z"])
                links.new(combine_node.outputs["Vector"], tex_node.inputs["Vector"])
                for i, dimension in enumerate(("X", "Y")):
                    if self.wrap[i]:
                        wrap_node = nodes.new(type="ShaderNodeMath")
                        wrap_node.operation = "WRAP"
                        wrap_node.inputs[2].default_value = 0.01 # Min Value
                        wrap_node.inputs[1].default_value = 0.99 # Max Value
                        links.new(separate_node.outputs[dimension], wrap_node.inputs["Value"])
                        links.new(wrap_node.outputs["Value"], combine_node.inputs[dimension])
                    else:
                        links.new(separate_node.outputs[dimension], combine_node.inputs[dimension])

            if use_transparency:
                material.blend_method = "HASHED"
                links.new(tex_node.outputs["Alpha"], bsdf_node.inputs["Alpha"])
                
            return material
            
        except:
            log.exception(f"Failed to create material mtl_{self.data:08X}")
            return None

    def calculateSize(self, replicate_tex_mirror_blender):
        def pow2(val):
            i = 1
            while i < val:
                i <<= 1
            return int(i)

        def powof(val):
            num, i = 1, 0
            while num < val:
                num <<= 1
                i += 1
            return int(i)

        log = getLogger("Tile.calculateSize")
        maxTxl, lineShift = 0, 0
        # FIXME: what is maxTxl? this whole function is rather mysterious, not sure how/why it works
        #texFmt 0 2 texSiz 0
        # RGBA CI 4b
        if (self.texFmt == 0 or self.texFmt == 2) and self.texSiz == 0:
            maxTxl = 4096
            lineShift = 4
        # texFmt 3 4 texSiz 0
        # IA I 4b
        elif (self.texFmt == 3 or self.texFmt == 4) and self.texSiz == 0:
            maxTxl = 8192
            lineShift = 4
        # texFmt 0 2 texSiz 1
        # RGBA CI 8b
        elif (self.texFmt == 0 or self.texFmt == 2) and self.texSiz == 1:
            maxTxl = 2048
            lineShift = 3
        # texFmt 3 4 texSiz 1
        # IA I 8b
        elif (self.texFmt == 3 or self.texFmt == 4) and self.texSiz == 1:
            maxTxl = 4096
            lineShift = 3
        # texFmt 0 3 texSiz 2
        # RGBA IA 16b
        elif (self.texFmt == 0 or self.texFmt == 3) and self.texSiz == 2:
            maxTxl = 2048
            lineShift = 2
        # texFmt 2 4 texSiz 2
        # CI I 16b
        elif (self.texFmt == 2 or self.texFmt == 4) and self.texSiz == 2:
            maxTxl = 2048
            lineShift = 0
        # texFmt 0 texSiz 3
        # RGBA 32b
        elif self.texFmt == 0 and self.texSiz == 3:
            maxTxl = 1024
            lineShift = 2
        else:
            log.warning(f"Unknown format for texture {self.current_texture_file_path} texFmt {self.texFmt} texSiz {self.texSiz}")
        
        self.lineSize << lineShift
        line_size = [self.lineSize, 0]
        tile_size = (self.rect.z - self.rect.x + 1, self.rect.w - self.rect.y + 1)
        mask_size = [1 << int(v) for v in self.mask]

        if line_size[0] > 0:
            line_size[1] = min(int(maxTxl / line_size[0]), tile_size[1])

        for i in range(2):
            if self.mask[i] > 0 and (mask_size[0] * mask_size[1]) <= maxTxl:
                self.dims[i] = mask_size[i]
            elif (tile_size[0] * tile_size[1]) <= maxTxl:
                self.dims[i] = tile_size[i]
            else:
                self.dims[i] = line_size[i]

            if self.mirror[i] and self.wrap[i]:
                clamp = tile_size[i]
            else:
                clamp = self.dims[i]

            if mask_size[i] > self.dims[i]:
                self.mask[i] = powof(self.dims[i])
                mask_size[i] = 1 << int(self.mask[i])
        
            if not self.wrap[i]:
                self.r_dims[i] = pow2(clamp)
            elif self.mirror[i]:
                self.r_dims[i] = pow2(mask_size[i])
            else:
                self.r_dims[i] = pow2(self.dims[i])

            self.shift[i] = 1.0

            if self.tshift[i] > 10:
                self.shift[i] = 1 << int(16 - self.tshift[i])
            elif self.tshift[i] > 0:
                self.shift[i] /= 1 << int(self.tshift[i])
        
            self.ratio[i] = (self.scale[i] * self.shift[i]) / self.r_dims[i] / 32
        
            if self.mirror[i] and replicate_tex_mirror_blender:
                self.ratio[i] /= 2
            self.offset[i] = self.rect[i]

        self.offset.y += 1.0

    def writePalette(self, file, segment, palSize):
        log = getLogger("Tile.writePalette")
        if not validOffset(segment, self.palette + palSize * 2 - 1):
            log.error(f"Segment offsets 0x{self.palette:X}-0x{self.palette + palSize * 2 - 1:X} are invalid, writing black palette to {self.current_texture_file_path} (has the segment data been loaded?)")
            for _ in range(palSize):
                file.write(pack("L", 0))
            self.write_error_encountered = True
            return
        seg, offset = splitOffset(self.palette)
        for i in range(palSize):
            color = unpack_from(">H", segment[seg], offset + i * 2)[0]
            r = int(255/31 * ((color >> 11) & 0b11111))
            g = int(255/31 * ((color >> 6) & 0b11111))
            b = int(255/31 * ((color >> 1) & 0b11111))
            a = 255 * (color & 1)
            file.write(pack("BBBB", b, g, r, a))

    def writeImageData(self, file, segment, replicate_tex_mirror_blender, fy=False, df=False):
        log = getLogger("Tile.writeImageData")
        if self.texSiz <= 3:
            bpp = (0.5,1,2,4)[self.texSiz] # bytes (not bits) per pixel
        else:
            log.warning(f"Unknown texSiz {self.texSiz} for texture {self.current_texture_file_path}, defaulting to 4 bytes per pixel")
            bpp = 4
        lineSize = self.r_dims[0] * bpp
        writeFallbackData = False
        if not validOffset(segment, self.data + int(self.r_dims[1] * lineSize) - 1):
            log.error(f"Segment offsets 0x{self.data:X}-0x{self.data + int(self.r_dims[1] * lineSize) - 1:X} are invalid, writing default fallback colors to {self.current_texture_file_path} (has the segment data been loaded?)")
            writeFallbackData = True
        if (self.texFmt,self.texSiz) not in (
            (0,2), (0,3), # RGBA16, RGBA32
            #(1,-1), # YUV ? "not used in z64 games"
            (2,0), (2,1), # CI4, CI8
            (3,0), (3,1), (3,2), # IA4, IA8, IA16
            (4,0), (4,1), # I4, I8
        ):
            log.error(f"Unknown fmt/siz combination {self.texFmt}/{self.texSiz} ({self.getFormatName()}?)")
            writeFallbackData = True
        if writeFallbackData:
            size = self.r_dims[0] * self.r_dims[1]
            for should_mirror in self.mirror:
                if should_mirror and replicate_tex_mirror_blender:
                    side *= 2
            for _ in range(size):
                if self.texFmt == 2: # CI (paletted)
                    file.write(pack("B", 0))
                else:
                    file.write(pack(">L", 0x000000FF))
            self.write_error_encountered = True
            return
        seg, offset = splitOffset(self.data)
        for i in range(self.r_dims[1]) if fy else reversed(range(self.r_dims[1])):
            off = offset + int(i * lineSize)
            line = []
            j = 0
            while j < int(self.r_dims[0] * bpp):
                if bpp < 2: # 0.5, 1
                    color = unpack_from("B", segment[seg], off + int(floor(j)))[0]
                    if bpp == 0.5:
                        color = ((color >> 4) if j % 1 == 0 else color) & 0xF
                elif bpp == 2:
                    color = unpack_from(">H", segment[seg], off + j)[0]
                else: # 4
                    color = unpack_from(">L", segment[seg], off + j)[0]
                if self.texFmt == 0: # RGBA
                    if self.texSiz == 2: # RGBA16
                        r = ((color >> 11) & 0b11111) * 255 // 31
                        g = ((color >> 6) & 0b11111) * 255 // 31
                        b = ((color >> 1) & 0b11111) * 255 // 31
                        a = (color & 1) * 255
                    elif self.texSiz == 3: # RGBA32
                        r = (color >> 24) & 0xFF
                        g = (color >> 16) & 0xFF
                        b = (color >> 8) & 0xFF
                        a = color & 0xFF
                elif self.texFmt == 2: # CI
                    if self.texSiz == 0: # CI4
                        p = color
                    elif self.texSiz == 1: # CI8
                        p = color
                elif self.texFmt == 3: # IA
                    if self.texSiz == 0: # IA4
                        r = g = b = (color >> 1) * 255 // 7
                        a = (color & 1) * 255
                    elif self.texSiz == 1: # IA8
                        r = g = b = (color >> 4) * 255 // 15
                        a = (color & 0xF) * 255 // 15
                    elif self.texSiz == 2: # IA16
                        r = g = b = color >> 8
                        a = color & 0xFF
                elif self.texFmt == 4: # I
                    if self.texSiz == 0: # I4
                        r = g = b = a = color * 255 // 15
                    elif self.texSiz == 1: # I8
                        r = g = b = a = color
                try:
                    if self.texFmt == 2: # CI
                        line.append(p)
                    else:
                        line.append((b << 24) | (g << 16) | (r << 8) | a)
                except UnboundLocalError:
                    log.error(f"Unknown format texFmt {self.texFmt} texSiz {self.texSiz}")
                    raise
                """
                if self.texFmt == 0x40 or self.texFmt == 0x48 or self.texFmt == 0x50:
                    line.append(a)
                else:
                    line.append((b << 24) | (g << 16) | (r << 8) | a)
                """
                j += bpp
            if self.texFmt == 2: # CI # in (0x40, 0x48, 0x50):
                file.write(pack("B" * len(line), *line))
            else:
                file.write(pack(">" + "L" * len(line), *line))
            if self.mirror[0] and replicate_tex_mirror_blender:
                line.reverse()
                if self.texFmt == 2: # CI # in (0x40, 0x48, 0x50):
                    file.write(pack("B" * len(line), *line))
                else:
                    file.write(pack(">" + "L" * len(line), *line))
        if self.mirror[1] and df == False and replicate_tex_mirror_blender:
            self.writeImageData(file, segment, not fy, True)


class Vertex:
    def __init__(self):
        self.pos = Vector([0, 0, 0])
        self.uv = Vector([0, 0])
        self.normal = Vector([0, 0, 0])
        self.color = [0, 0, 0, 0]
        self.limb = None

    def read(self, segment, offset, scale_factor):
        log = getLogger("Vertex.read")
        if not validOffset(segment, offset + 16):
            log.warning(f"Invalid segmented offset 0x{offset + 16:X} for vertex")
            return
        seg, offset = splitOffset(offset)
        self.pos = Vector(unpack_from(">hhh", segment[seg], offset)).xzy
        self.pos.y = -self.pos.y
        self.pos *= scale_factor
        self.uv = Vector(unpack_from(">hh", segment[seg], offset + 8))
        self.normal = Vector(unpack_from("bbb", segment[seg], offset + 12)).xzy
        self.normal.y = -self.normal.y
        self.normal /= 128
        self.color = [min(segment[seg][offset + 12 + i] / 255, 1.0) for i in range(4)]


class Mesh:
    def __init__(self):
        self.verts, self.uvs, self.colors, self.faces = [], [], [], []
        self.faces_use_smooth = []
        self.vgroups = {}
        # import normals
        self.normals = []

    def create(self, name_format, hierarchy, offset, use_normals, prefix=""):
        log = getLogger("Mesh.create")
        if len(self.faces) == 0:
            log.trace(f"Skipping empty mesh {offset:08X}")
            if self.verts:
                log.warning("Discarding unused vertices, no faces")
            return
        log.trace(f"Creating mesh {offset:08X}")

        me_name = prefix + (name_format % f"me_{offset:08X}")
        me = bpy.data.meshes.new(me_name)
        ob = bpy.data.objects.new(f"{prefix}{name_format % f'ob_{offset:08X}'}", me)
        bpy.context.scene.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        bm = bmesh.new()
        
        for vert in self.verts:
            bm.verts.new(vert)
        bm.verts.ensure_lookup_table()

        color_sets = [self.colors[x:x+3] for x in range(0, len(self.colors), 3)]
        uv_sets = [self.uvs[x:x+4] for x in range(0, len(self.uvs), 4)]
        color_layer = bm.loops.layers.color.new("Col")
        uv_layer = bm.loops.layers.uv.new("UVMap")

        for face, smooth, color_set, uv_set in zip(self.faces, self.faces_use_smooth, color_sets, uv_sets):
            verts = [bm.verts[x] for x in face]

            # Don't make a triangle if it's between only two verts
            if verts[0]==verts[1] or verts[1]==verts[2] or verts[0]==verts[2]:
                continue

            new_face = bm.faces.new(verts)
            new_face.smooth = smooth

            material = uv_set[0]
            if material:
                if material.name not in me.materials:
                    me.materials.append(material)
                index = [x.name for x in me.materials].index(material.name)
                new_face.material_index = index

            for loop, color, uv in zip(new_face.loops, color_set, uv_set[1:]):
                loop[color_layer] = color
                loop[uv_layer].uv = uv

        bm.to_mesh(me)
        bm.free()

        me.calc_normals()
        me.validate()
        me.update()

        log.debug(f"me =\n{me!r}")
        log.debug(f"verts =\n{self.verts!r}")
        log.debug(f"faces =\n{self.faces!r}")
        log.debug(f"normals =\n{self.normals!r}")

        if use_normals:
            # FIXME: make sure normals are set in the right order
            # FIXME: duplicate faces make normal count not the loop count
            loop_normals = []
            for face_normals in self.normals:
                loop_normals.extend(n for vi,n in face_normals)
            me.use_auto_smooth = True
            try:
                me.normals_split_custom_set(loop_normals)
            except:
                log.exception("normals_split_custom_set failed, known issue due to duplicate faces")

        if hierarchy:
            for name, vgroup in self.vgroups.items():
                grp = ob.vertex_groups.new(name=name)
                for v in vgroup:
                    grp.add([v], 1.0, "REPLACE")
            ob.parent = hierarchy.armature
            mod = ob.modifiers.new(hierarchy.name, "ARMATURE")
            mod.object = hierarchy.armature
            mod.use_bone_envelopes = False
            mod.use_vertex_groups = True
            mod.show_in_editmode = True
            mod.show_on_cage = True


class Limb:
    def __init__(self):
        self.parent, self.child, self.sibling = -1, -1, -1
        self.pos = Vector([0, 0, 0])
        self.near, self.far = 0x00000000, 0x00000000
        self.poseBone = None
        self.poseLocPath, self.poseRotPath = None, None
        self.poseLoc, self.poseRot = Vector([0, 0, 0]), None

    def read(self, segment, offset, actuallimb, BoneCount, scale_factor):
        seg, offset = splitOffset(offset)

        rot_offset = offset & 0xFFFFFF
        rot_offset += (0 * (BoneCount * 6 + 8));

        self.pos = Vector(unpack_from(">hhh", segment[seg], offset)).xzy
        self.pos.y = -self.pos.y
        self.pos *= scale_factor
        self.child, self.sibling = unpack_from("bb", segment[seg], offset + 6)
        self.near, self.far = unpack_from(">LL", segment[seg], offset + 8)

        self.poseLoc = Vector(unpack_from(">hhh", segment[seg], rot_offset))
        getLogger("Limb.read").trace(f"      Limb {actuallimb!r}: {self.poseLoc.x:f},{self.poseLoc.z:f},{self.poseLoc.y:f}")

class Hierarchy:
    def __init__(self):
        self.name, self.offset = "", 0x00000000
        self.limbCount, self.dlistCount = 0x00, 0x00
        self.limb = []
        self.armature = None

    def read(self, segment, offset, scale_factor, prefix=""):
        log = getLogger("Hierarchy.read")
        self.dlistCount = None
        if not validOffset(segment, offset + 5):
            log.error(f"Invalid segmented offset 0x{offset + 5:X} for hierarchy")
            return False
        if not validOffset(segment, offset + 9):
            log.warning(f"Invalid segmented offset 0x{offset + 9:X} for hierarchy (incomplete header), still trying to import ignoring dlistCount")
            self.dlistCount = 1
        self.name = f"{prefix}sk_{offset:08X}"
        self.offset = offset
        seg, offset = splitOffset(offset)
        limbIndex_offset = unpack_from(">L", segment[seg], offset)[0]
        if not validOffset(segment, limbIndex_offset):
            log.error(f"        ERROR:  Limb index table 0x{limbIndex_offset:08X} out of range")
            return False
        limbIndex_seg, limbIndex_offset = splitOffset(limbIndex_offset)
        self.limbCount = segment[seg][offset + 4]
        if not self.dlistCount:
            self.dlistCount = segment[seg][offset + 8]
        for i in range(self.limbCount):
            limb_offset = unpack_from(">L", segment[limbIndex_seg], limbIndex_offset + 4 * i)[0]
            limb = Limb()
            limb.index = i
            self.limb.append(limb)
            if validOffset(segment, limb_offset + 12):
                limb.read(segment, limb_offset, i, self.limbCount, scale_factor)
            else:
                log.error(f"        ERROR:  Limb 0x{i:02X} offset 0x{limb_offset:08X} out of range")
        self.limb[0].pos = Vector([0, 0, 0])
        self.initLimbs(0x00)
        return True

    def create(self):
        rx, ry, rz = 90,0,0
        if (bpy.context.active_object):
            bpy.ops.object.mode_set(mode="OBJECT", toggle=False)
        bpy.ops.object.select_all(action="DESELECT")
        self.armature = bpy.data.objects.new(self.name, bpy.data.armatures.new(f"{self.name}_armature"))
        self.armature.show_in_front = True
        self.armature.data.display_type = "STICK"
        bpy.context.scene.collection.objects.link(self.armature)
        bpy.context.view_layer.objects.active = self.armature
        bpy.ops.object.mode_set(mode="EDIT", toggle=False)
        for i in range(self.limbCount):
            bone = self.armature.data.edit_bones.new(f"limb_{i:02}")
            bone.use_deform = True
            bone.head = self.limb[i].pos

        for i in range(self.limbCount):
            bone = self.armature.data.edit_bones[f"limb_{i:02}"]
            if (self.limb[i].parent != -1):
                bone.parent = self.armature.data.edit_bones[f"limb_{self.limb[i].parent:02}"]
                bone.use_connect = False
            bone.tail = bone.head + Vector([0, 0, 0.0001])
        bpy.ops.object.mode_set(mode="OBJECT")

    def initLimbs(self, i):
        if (self.limb[i].child > -1 and self.limb[i].child != i):
            self.limb[self.limb[i].child].parent = i
            self.limb[self.limb[i].child].pos += self.limb[i].pos
            self.initLimbs(self.limb[i].child)
        if (self.limb[i].sibling > -1 and self.limb[i].sibling != i):
            self.limb[self.limb[i].sibling].parent = self.limb[i].parent
            self.limb[self.limb[i].sibling].pos += self.limb[self.limb[i].parent].pos
            self.initLimbs(self.limb[i].sibling)

    def getMatrixLimb(self, offset):
        j = 0
        index = (offset & 0x00FFFFFF) / 0x40
        for i in range(self.limbCount):
            if self.limb[i].near != 0:
                if (j == index):
                    return self.limb[i]
                j += 1
        return self.limb[0]


class F3DZEX:
    def __init__(self, detected_display_lists_use_transparency, config, prefix=""):
        self.prefix = prefix
        self.config = config

        self.use_transparency = detected_display_lists_use_transparency
        self.alreadyRead = []
        self.segment, self.vbuf, self.tile = [], [], []
        self.geometryModeFlags = set()

        self.animTotal = 0
        self.TimeLine = 0
        self.TimeLinePosition = 0
        self.displaylists = []

        for _ in range(16):
            self.alreadyRead.append([])
            self.segment.append([])
            self.vbuf.append(Vertex())
        for _ in range(2):
            self.tile.append(Tile())
            pass#self.vbuf.append(Vertex())
        for _ in range(14 + 32):
            pass#self.vbuf.append(Vertex())
        while len(self.vbuf) < 32:
            self.vbuf.append(Vertex())
        self.curTile = 0
        self.material = []
        self.hierarchy = []
        self.resetCombiner()

    def loaddisplaylists(self, path):
        log = getLogger("F3DZEX.loaddisplaylists")
        if not os.path.isfile(path):
            log.info(f"Did not find {path} (use to manually set offsets of display lists to import)")
            self.displaylists = []
            return
        try:
            with open(path, "r") as file:
                self.displaylists = file.readlines()
            log.info("Loaded the display list list successfully!")
        except:
            log.exception("Could not read displaylists.txt")

    def loadSegment(self, seg, path):
        try:
            with open(path, "rb") as file:
                self.segment[seg] = file.read()
        except:
            getLogger("F3DZEX.loadSegment").error(f"Could not load segment 0x{seg:02X} data from {path}")
            pass

    def locateHierarchies(self):
        log = getLogger("F3DZEX.locateHierarchies")
        data = self.segment[0x06]
        for i in range(0, len(data)-11, 4):
            # test for header "bboooooo pp000000 xx000000": if segment bb=0x06 and offset oooooo 4-aligned and not zero parts (pp!=0)
            if data[i] == 0x06 and (data[i+3] & 3) == 0 and data[i+4] != 0:
                offset = unpack_from(">L", data, i)[0] & 0x00FFFFFF
                if offset < len(data):
                    # each Limb index entry is 4 bytes starting at offset
                    offset_end = offset + (data[i+4] << 2)
                    if offset_end <= len(data):
                        j = offset
                        while j < offset_end:
                            # test for limb entry "bboooooo": valid limb entry table as long as segment bb=0x06 and offset oooooo 4-aligned and offset is valid
                            if data[j] != 0x06 or (data[j+3] & 3) != 0 or (unpack_from(">L", data, j)[0] & 0x00FFFFFF) > len(data):
                                break
                            j += 4
                        if (j == i):
                            j |= 0x06000000
                            log.info(f"    hierarchy found at 0x{j:08X}")
                            h = Hierarchy()
                            if h.read(self.segment, j, self.config["scale_factor"], prefix=self.prefix):
                                self.hierarchy.append(h)
                            else:
                                log.warning(f"Skipping hierarchy at 0x{j:08X}")

    def locateAnimations(self):
        log = getLogger("F3DZEX.locateAnimations")
        data = self.segment[0x06]
        self.animation = []
        self.offsetAnims = []
        self.durationAnims = []
        for i in range(0, len(data)-15, 4):
            # detect animation header
            # ffff0000 rrrrrrrr iiiiiiii llll0000
            # FIXME: data[i] == 0 but should be first byte of ffff
            # FIXME: data[i+1] > 1 but why not 1 (or 0)
            if ((data[i] == 0) and (data[i+1] > 1) and
                 (data[i+2] == 0) and (data[i+3] == 0) and
                 (data[i+4] == 0x06) and
                 (((data[i+5] << 16)|(data[i+6] << 8)|data[i+7]) < len(data)) and
                 (data[i+8] == 0x06) and
                 (((data[i+9] << 16)|(data[i+10] << 8)|data[i+11]) < len(data)) and
                 (data[i+14] == 0) and (data[i+15] == 0)):
                log.info(f"          Anims found at {i:08X} Frames: {data[i+1] & 0x00FFFFFF}")
                self.animation.append(i)
                self.offsetAnims.append(i)
                self.offsetAnims[self.animTotal] = (0x06 << 24) | i
                # FIXME: it's two bytes, not one
                self.durationAnims.append(data[i+1] & 0x00FFFFFF)
                self.animTotal += 1
        if(self.animTotal > 0):
                log.info(f"          Total Anims                         : {self.animTotal}")

    def locateExternAnimations(self):
        log = getLogger("F3DZEX.locateExternAnimations")
        data = self.segment[0x0F]
        self.animation = []
        self.offsetAnims = []
        for i in range(0, len(data)-15, 4):
            if ((data[i] == 0) and (data[i+1] > 1) and
                 (data[i+2] == 0) and (data[i+3] == 0) and
                 (data[i+4] == 0x06) and
                 (((data[i+5] << 16)|(data[i+6] << 8)|data[i+7]) < len(data)) and
                 (data[i+8] == 0x06) and
                 (((data[i+9] << 16)|(data[i+10] << 8)|data[i+11]) < len(data)) and
                 (data[i+14] == 0) and (data[i+15] == 0)):
                log.info(f"          Ext Anims found at {i:08X} Frames: {data[i+1] & 0x00FFFFFF}")
                self.animation.append(i)
                self.offsetAnims.append(i)
                self.offsetAnims[self.animTotal] = (0x0F << 24) | i
                self.animTotal += 1
        if(self.animTotal > 0):
            log.info(f"        Total Anims                   : {self.animTotal}")

    def locateLinkAnimations(self, anim_to_play):
        log = getLogger("F3DZEX.locateLinkAnimations")
        data = self.segment[0x04]
        self.animation = []
        self.offsetAnims = []
        self.animFrames = []
        self.animTotal = -1
        if (len( self.segment[0x04] ) > 0):
            if (self.config["majora_anims"]):
                for i in range(0xD000, 0xE4F8, 8):
                    self.animTotal += 1
                    self.animation.append(self.animTotal)
                    self.animFrames.append(self.animTotal)
                    self.offsetAnims.append(self.animTotal)
                    self.offsetAnims[self.animTotal]     = unpack_from(">L", data, i + 4)[0]
                    self.animFrames[self.animTotal] = unpack_from(">h", data, i)[0]
                    log.debug(f"- Animation #{self.animTotal+1} offset: {self.offsetAnims[self.animTotal]:07X} frames: {self.animFrames[self.animTotal]}")
            else:
                for i in range(0x2310, 0x34F8, 8):
                    self.animTotal += 1
                    self.animation.append(self.animTotal)
                    self.animFrames.append(self.animTotal)
                    self.offsetAnims.append(self.animTotal)
                    self.offsetAnims[self.animTotal]     = unpack_from(">L", data, i + 4)[0]
                    self.animFrames[self.animTotal] = unpack_from(">h", data, i)[0]
                    log.debug(f"- Animation #{self.animTotal+1} offset: {self.offsetAnims[self.animTotal]:07X} frames: {self.animFrames[self.animTotal]}")
        log.info("         Link has come to town!!!!")
        if ( (len( self.segment[0x07] ) > 0) and (self.animTotal > 0)):
            self.buildLinkAnimations(self.hierarchy[0], 0, anim_to_play)

    def importJFIF(self, data, initPropsOffset, name_format="bg_%08X"):
        log = getLogger("F3DZEX.importJFIF")
        (   imagePtr,
            unknown, unknown2,
            background_width, background_height,
            imageFmt, imageSiz, imagePal, imageFlip
        ) = struct.unpack_from(">IIiHHBBHH", data, initPropsOffset)
        t = Tile()
        t.texFmt = imageFmt
        t.texSiz = imageSiz
        log.debug(
            "JFIF background image init properties\n"
            f"imagePtr=0x{imagePtr:X} size={background_width}x{background_height} fmt={imageFmt}, siz={imageSiz} ({t.getFormatName()}) imagePal={imagePal} imageFlip={imageFlip}"
        )
        if imagePtr >> 24 != 0x03:
            log.error(f"Skipping JFIF background image, pointer 0x{imagePtr:08X} is not in segment 0x03")
            return False
        jfifDataStart = imagePtr & 0xFFFFFF
        # read header just for sanity checks
        # source: CloudModding wiki https://wiki.cloudmodding.com/oot/JFIF_Backgrounds
        (   marker_begin,
            marker_begin_header, header_length,
            jfif, null, version,
            dens, densx, densy,
            thumbnail_width, thumbnail_height,
            marker_end_header
        ) = struct.unpack_from(">HHHIBHBHHBBH", data, jfifDataStart)
        badJfif = []
        if marker_begin != 0xFFD8:
            badJfif.append(f"Expected marker_begin=0xFFD8 instead of 0x{marker_begin:04X}")
        if marker_begin_header != 0xFFE0:
            badJfif.append(f"Expected marker_begin_header=0xFFE0 instead of 0x{marker_begin_header:04X}")
        if header_length != 16:
            badJfif.append(f"Expected header_length=16 instead of {header_length}=0x{header_length:04X}")
        if jfif != 0x4A464946: # JFIF
            badJfif.append(f'Expected jfif=0x4A464946="JFIF" instead of 0x{jfif:08X}')
        if null != 0:
            badJfif.append(f"Expected null=0 instead of 0x{null:02X}")
        if version != 0x0101:
            badJfif.append(f"Expected version=0x0101 instead of 0x{version:04X}")
        if dens != 0:
            badJfif.append(f"Expected dens=0 instead of {dens}=0x{dens:02X}")
        if densx != 1:
            badJfif.append(f"Expected densx=1 instead of {densx}=0x{densx:04X}")
        if densy != 1:
            badJfif.append(f"Expected densy=1 instead of {densy}=0x{densy:04X}")
        if thumbnail_width != 0:
            badJfif.append(f"Expected thumbnail_width=0 instead of {thumbnail_width}=0x{thumbnail_width:02X}")
        if thumbnail_height != 0:
            badJfif.append(f"Expected thumbnail_height=0 instead of {thumbnail_height}=0x{thumbnail_height:02X}")
        if marker_end_header != 0xFFDB:
            badJfif.append(f"Expected marker_end_header=0xFFDB instead of 0x{marker_end_header:04X}")
        if badJfif:
            log.error(f"Bad JFIF format for background image at 0x{jfifDataStart:X}:")
            for badJfifMessage in badJfif:
                log.error(badJfifMessage)
            return False
        jfifData = None
        i = jfifDataStart
        for i in range(jfifDataStart, len(data)-1):
            if data[i] == 0xFF and data[i+1] == 0xD9:
                jfifData = data[jfifDataStart:i+2]
                break
        if jfifData is None:
            log.error(f"Did not find end marker 0xFFD9 in background image at 0x{jfifDataStart:X}")
            return False
        texture_path = os.path.join(self.config['fpath'], "textures")
        try:
            os.mkdir(texture_path)
        except FileExistsError:
            pass
        except:
            log.exception(f"Could not create textures directory {texture_path}")
            pass
        jfifPath = os.path.join(self.config['fpath'], "textures", f"jfif_{name_format % jfifDataStart}.jfif")
        with open(jfifPath, "wb") as f:
            f.write(jfifData)
        log.info(f"Copied jfif image to {jfifPath}")
        jfifImage = load_image(jfifPath)
        me = bpy.data.meshes.new(f"{self.prefix}{name_format % jfifDataStart}")
        me.vertices.add(4)
        cos = (
            (background_width, 0),
            (0,                0),
            (0,                background_height),
            (background_width, background_height),
        )
        import bmesh
        bm = bmesh.new()
        transform = Matrix.Scale(self.config["scale_factor"], 4)
        bm.faces.new(bm.verts.new(transform * Vector((cos[i][0], 0, cos[i][1]))) for i in range(4))
        bm.to_mesh(me)
        bm.free()
        del bmesh
        me.uv_textures.new().data[0].image = jfifImage
        ob = bpy.data.objects.new(self.prefix + (name_format % jfifDataStart), me)
        ob.location.z = max(max(v.co.z for v in obj.data.vertices) for obj in bpy.context.scene.objects if obj.type == "MESH")
        bpy.context.scene.collection.objects.link(ob)
        return ob

    def importMap(self):
        if self.config["import_strategy"] == "NO_DETECTION":
            self.importMapWithHeaders()
        elif self.config["import_strategy"] == "BRUTEFORCE":
            self.searchAndImport(3, False)
        elif self.config["import_strategy"] == "SMART":
            self.importMapWithHeaders()
            self.searchAndImport(3, True)
        elif self.config["import_strategy"] == "TRY_EVERYTHING":
            self.importMapWithHeaders()
            self.searchAndImport(3, False)

    def importMapWithHeaders(self):
        log = getLogger("F3DZEX.importMapWithHeaders")
        data = self.segment[0x03]
        for i in range(0, len(data), 8):
            if data[i] == 0x0A:
                mapHeaderSegment = data[i+4]
                if mapHeaderSegment != 0x03:
                    log.warning(f"Skipping map header located in segment 0x{mapHeaderSegment:02X}, referenced by command at 0x{i:X}")
                    continue
                # mesh header offset 
                mho = (data[i+5] << 16) | (data[i+6] << 8) | data[i+7]
                if not mho < len(data):
                    log.error(f"Mesh header offset 0x{mho:X} is past the room file size, skipping")
                    continue
                type = data[mho]
                log.info(f"            Mesh Type: {type}")
                if type == 0:
                    if mho + 12 > len(data):
                        log.error(f"Mesh header at 0x{mho:X} of type {type} extends past the room file size, skipping")
                        continue
                    count = data[mho+1]
                    startSeg = data[mho+4]
                    start = (data[mho+5] << 16) | (data[mho+6] << 8) | data[mho+7]
                    endSeg = data[mho+8]
                    end = (data[mho+9] << 16) | (data[mho+10] << 8) | data[mho+11]
                    if startSeg != endSeg:
                        log.error(f"Mesh header at 0x{mho:X} of type {type} has start and end in different segments 0x{startSeg:02X} and 0x{endSeg:02X}, skipping")
                        continue
                    if startSeg != 0x03:
                        log.error(f"Skipping mesh header at 0x{mho:X} of type {type}: entries are in segment 0x{startSeg:02X}")
                        continue
                    log.info(f"Reading {count} display lists from 0x{start:X} to 0x{end:X}")
                    for j in range(start, end, 8):
                        opa, xlu = unpack_from(">LL", data, j)
                        if opa:
                            self.use_transparency = False
                            self.buildDisplayList(None, [None], opa, mesh_name_format="%s_opa")
                        if xlu:
                            self.use_transparency = True
                            self.buildDisplayList(None, [None], xlu, mesh_name_format="%s_xlu")
                elif type == 1:
                    format = data[mho+1]
                    entrySeg = data[mho+4]
                    entry = (data[mho+5] << 16) | (data[mho+6] << 8) | data[mho+7]
                    if entrySeg == 0x03:
                        opa, xlu = unpack_from(">LL", data, entry)
                        if opa:
                            self.use_transparency = False
                            self.buildDisplayList(None, [None], opa, mesh_name_format="%s_opa")
                        if xlu:
                            self.use_transparency = True
                            self.buildDisplayList(None, [None], xlu, mesh_name_format="%s_xlu")
                    else:
                        log.error(f"Skipping mesh header at 0x{mho:X} of type {type}: entry is in segment 0x{entrySeg:02X}")
                    if format == 1:
                        if not self.importJFIF(data, mho + 8):
                            log.error(f"Failed to import jfif background image, mesh header at 0x{mho:X} of type 1 format 1")
                    elif format == 2:
                        background_count = data[mho + 8]
                        backgrounds_array = unpack_from(">L", data, mho + 0xC)[0]
                        if backgrounds_array >> 24 == 0x03:
                            backgrounds_array &= 0xFFFFFF
                            for i in range(background_count):
                                bg_record_offset = backgrounds_array + i * 0x1C
                                unk82, bgid = struct.unpack_from(">HB", data, bg_record_offset)
                                if unk82 != 0x0082:
                                    log.error(f"Skipping JFIF: mesh header at 0x{mho:X} type 1 format 2 background record entry #{i} at 0x{bg_record_offset:X} expected unk82=0x0082, not 0x{unk82:04X}")
                                    continue
                                ob = self.importJFIF(
                                    data, bg_record_offset + 4,
                                    name_format=f"bg_{i}_%08X"
                                )
                                ob.location.y -= self.config["scale_factor"] * 100 * i
                                if not ob:
                                    log.error(f"Failed to import jfif background image from record entry #{i} at 0x{bg_record_offset:X}, mesh header at 0x{mho:X} of type 1 format 2")
                        else:
                            log.error(f"Skipping mesh header at 0x{mho:X} of type 1 format 2: backgrounds_array=0x{backgrounds_array:08X} is not in segment 0x03")
                    else:
                        log.error(f"Unknown format {format} for mesh type 1 in mesh header at 0x{mho:X}")
                elif type == 2:
                    if mho + 12 > len(data):
                        log.error(f"Mesh header at 0x{mho:X} of type {type} extends past the room file size, skipping")
                        continue
                    count = data[mho+1]
                    startSeg = data[mho+4]
                    start = (data[mho+5] << 16) | (data[mho+6] << 8) | data[mho+7]
                    endSeg = data[mho+8]
                    end = (data[mho+9] << 16) | (data[mho+10] << 8) | data[mho+11]
                    if startSeg != endSeg:
                        log.error(f"Mesh header at 0x{mho:X} of type {type} has start and end in different segments 0x{startSeg:02X} and 0x{endSeg:02X}, skipping")
                        continue
                    if startSeg != 0x03:
                        log.error(f"Skipping mesh header at 0x{mho:X} of type {type}: entries are in segment 0x{startSeg:02X}")
                        continue
                    log.info(f"Reading {count} display lists from 0x{start:X} to 0x{end:X}")
                    for j in range(start, end, 16):
                        opa, xlu = unpack_from(">LL", data, j+8)
                        if opa:
                            self.use_transparency = False
                            self.buildDisplayList(None, [None], opa, mesh_name_format="%s_opa")
                        if xlu:
                            self.use_transparency = True
                            self.buildDisplayList(None, [None], xlu, mesh_name_format="%s_xlu")
                else:
                    log.error(f"Unknown mesh type {type} in mesh header at 0x{mho:X}")
            elif (data[i] == 0x14):
                return
        log.warning("Map headers ended unexpectedly")

    def importObj(self):
        log = getLogger("F3DZEX.importObj")
        log.info("Locating hierarchies...")
        self.locateHierarchies()


        if len(self.displaylists) != 0:
            log.info("Importing display lists defined in displaylists.txt")
            for offsetStr in self.displaylists:
                while offsetStr and offsetStr[-1] in ("\r","\n"):
                    offsetStr = offsetStr[:-1]
                if offsetStr.isdecimal():
                    log.warning(f"Reading offset {offsetStr} as hexadecimal, NOT decimal")
                if len(offsetStr) > 2 and offsetStr[:2] == "0x":
                    offsetStr = offsetStr[2:]
                try:
                    offset = int(offsetStr, 16)
                except ValueError:
                    log.error(f"Could not parse {offsetStr} from displaylists.txt as hexadecimal, skipping entry")
                    continue
                if (offset & 0xFF000000) == 0:
                    log.info(f"Defaulting segment for offset 0x{offset:X} to 6")
                    offset |= 0x06000000
                log.info(f"Importing display list 0x{offset:08X} (from displaylists.txt)")
                self.buildDisplayList(None, 0, offset)

        anim_to_play = 1 if self.config["load_animations"] else 0

        for hierarchy in self.hierarchy:
            log.info(f"Building hierarchy '{hierarchy.name}'...")
            hierarchy.create()
            for i in range(hierarchy.limbCount):
                limb = hierarchy.limb[i]
                if limb.near != 0:
                    if validOffset(self.segment, limb.near):
                        log.info(f"    0x{i:02X} : building display lists...")
                        self.resetCombiner()
                        self.buildDisplayList(hierarchy, limb, limb.near)
                    else:
                        log.info(f"    0x{i:02X} : out of range")
                else:
                    log.info(f"    0x{i:02X} : n/a")
        if len(self.hierarchy) > 0:
            bpy.context.view_layer.objects.active = self.hierarchy[0].armature
            self.hierarchy[0].armature.select_set(True)
            bpy.ops.object.mode_set(mode="POSE", toggle=False)
            if (anim_to_play > 0):
                bpy.context.scene.frame_end = 1
                if(self.config["external_animes"] and len(self.segment[0x0F]) > 0):
                    self.locateExternAnimations()
                else:
                    self.locateAnimations()
                if len(self.animation) > 0:
                    for h in self.hierarchy:
                        if h.armature.animation_data is None:
                            h.armature.animation_data_create()
                    # use the hierarchy with most bones
                    # this works for building any animation regardless of its target skeleton (bone positions) because all limbs are named limb_XX, so the hierarchy with most bones has bones with same names as every other armature
                    # and the rotation and root location animated values don't rely on the actual armature used
                    # and in blender each action can be used for any armature, vertex groups/bone names just have to match
                    # this is useful for iron knuckles and anything with several hierarchies, although an unedited iron kunckles zobj won't work
                    hierarchy = max(self.hierarchy, key=lambda h:h.limbCount)
                    armature = hierarchy.armature
                    log.info(f"Building animations using armature {armature.data.name} in {armature.name}")
                    for i in range(len(self.animation)):
                        anim_to_play = i + 1
                        log.info(f"   Loading animation {anim_to_play}/{len(self.animation)} 0x{self.offsetAnims[anim_to_play-1]:08X}")
                        action = bpy.data.actions.new(f"{self.prefix}anim{anim_to_play}_{self.durationAnims[i]}")
                        action.use_fake_user = True
                        armature.animation_data.action = action
                        self.buildAnimation(hierarchy, anim_to_play)
                    for h in self.hierarchy:
                        h.armature.animation_data.action = action
                    bpy.context.scene.frame_end = max(self.durationAnims)
                else:
                    self.locateLinkAnimations(anim_to_play)
            else:
                log.info("    Load anims OFF.")
            bpy.ops.object.mode_set(mode="OBJECT", toggle=False)

        if self.config["import_strategy"] == "NO_DETECTION":
            pass
        elif self.config["import_strategy"] == "BRUTEFORCE":
            self.searchAndImport(6, False)
        elif self.config["import_strategy"] == "SMART":
            self.searchAndImport(6, True)
        elif self.config["import_strategy"] == "TRY_EVERYTHING":
            self.searchAndImport(6, False)

    def searchAndImport(self, segment, skipAlreadyRead):
        log = getLogger("F3DZEX.searchAndImport")
        data = self.segment[segment]
        self.use_transparency = self.config["detected_display_lists_use_transparency"]
        log.info(f"Searching for {'non-read' if skipAlreadyRead else 'any'} display lists in segment 0x{segment:02X} (materials with transparency: {'yes' if self.use_transparency else 'no'}")
        log.warning(f"If the imported geometry is weird/wrong, consider using displaylists.txt to manually define the display lists to import!")
        validOpcodesStartIndex = 0
        validOpcodesSkipped = set()
        for i in range(0, len(data), 8):
            opcode = data[i]
            # valid commands are 0x00-0x07 and 0xD3-0xFF
            # however, could be not considered valid:
            # 0x07 G_QUAD
            # 0xEC G_SETCONVERT (YUV-related)
            # 0xE4 G_TEXRECT, 0xF6 G_FILLRECT (2d overlay)
            # 0xEB, 0xEE, 0xEF, 0xF1 ("unimplemented -> rarely used" being the reasoning)
            # but filtering out those hurts the resulting import
            isValid = (opcode <= 0x07 or opcode >= 0xD3) #and opcode not in (0x07,0xEC,0xE4,0xF6,0xEB,0xEE,0xEF,0xF1)
            if isValid and self.config["detected_display_lists_consider_unimplemented_invalid"]:
                
                isValid = opcode not in (0x07,0xE5,0xEC,0xD3,0xDB,0xDC,0xDD,0xE0,0xE5,0xE9,0xF6,0xF8)
                if not isValid:
                    validOpcodesSkipped.add(opcode)
            if not isValid:
                validOpcodesStartIndex = None
            elif validOpcodesStartIndex is None:
                validOpcodesStartIndex = i
            # if this command means "end of dlist"
            if (opcode == 0xDE and data[i+1] != 0) or opcode == 0xDF:
                # build starting at earliest valid opcode
                log.debug(f"Found opcode 0x{opcode:X} at 0x{i:X}, building display list from 0x{validOpcodesStartIndex:X}")
                self.buildDisplayList(
                    None, [None], (segment << 24) | validOpcodesStartIndex,
                    mesh_name_format = "%s_detect",
                    skipAlreadyRead = skipAlreadyRead,
                    extraLenient = True
                )
                validOpcodesStartIndex = None
        if validOpcodesSkipped:
            log.info(f"Valid opcodes {','.join(f'0x{opcode:02X}' for opcode in sorted(validOpcodesSkipped))} considered invalid because unimplemented (meaning rare)")

    def resetCombiner(self):
        self.primColor = Vector([1.0, 1.0, 1.0, 1.0])
        self.envColor = Vector([1.0, 1.0, 1.0, 1.0])
        self.vertexColor = Vector([1.0, 1.0, 1.0, 1.0])
        self.shadeColor = Vector([1.0, 1.0, 1.0])

    def checkUseNormals(self):
        return self.config["vertex_mode"] == "NORMALS" or (self.config["vertex_mode"] == "AUTO" and "G_LIGHTING" in self.geometryModeFlags)

    def getCombinerColor(self):
        def multiply_color(v1, v2):
            return Vector(x * y for x, y in zip(v1, v2))
        cc = Vector([1.0, 1.0, 1.0, 1.0])
        # TODO: these have an effect even if vertexMode == "NONE" ?
        if self.config["enable_prim_color"]:
            cc = multiply_color(cc, self.primColor)
        if self.config["enable_env_color"]:
            cc = multiply_color(cc, self.envColor)
        # TODO: assume G_LIGHTING means normals if set, and colors if clear, but G_SHADE may play a role too?
        if self.config["vertex_mode"] == "COLORS" or (self.config["vertex_mode"] == "AUTO" and "G_LIGHTING" not in self.geometryModeFlags):
            cc = multiply_color(cc, self.vertexColor.to_4d())
        elif self.checkUseNormals():
            cc = multiply_color(cc, self.shadeColor.to_4d())
        
        return cc

    def buildDisplayList(self, hierarchy, limb, offset, mesh_name_format="%s", skipAlreadyRead=False, extraLenient=False):
        log = getLogger("F3DZEX.buildDisplayList")
        segment = offset >> 24
        segmentMask = segment << 24
        data = self.segment[segment]

        startOffset = offset & 0x00FFFFFF
        endOffset = len(data)
        if skipAlreadyRead:
            log.trace(f"is 0x{startOffset:X} in {self.alreadyRead[segment]!r} ?")
            for fromOffset,toOffset in self.alreadyRead[segment]:
                if fromOffset <= startOffset and startOffset <= toOffset:
                    log.debug(f"Skipping already read dlist at 0x{startOffset:X}")
                    return
                if startOffset <= fromOffset:
                    if endOffset > fromOffset:
                        endOffset = fromOffset
                        log.debug(f"Shortening dlist to end at most at 0x{endOffset:X}, at which point it was read already")
            log.trace("no it is not")

        def buildRec(offset):
            self.buildDisplayList(hierarchy, limb, offset, mesh_name_format=mesh_name_format, skipAlreadyRead=skipAlreadyRead)

        mesh = Mesh()
        has_tex = False
        material = None
        if hierarchy:
            matrix = [limb]
        else:
            matrix = [None]

        log.debug(f"Reading dlists from 0x{segmentMask | startOffset:08X}")
        for i in range(startOffset, endOffset, 8):
            w0, w1 = unpack_from(">LL", data, i)
            # G_NOOP
            if data[i] == 0x00:
                pass
            elif data[i] == 0x01:
                count = (w0 >> 12) & 0xFF
                index = ((w0 & 0xFF) >> 1) - count
                vaddr = w1
                if validOffset(self.segment, vaddr + int(16 * count) - 1):
                    for j in range(count):
                        self.vbuf[index + j].read(self.segment, vaddr + 16 * j, self.config["scale_factor"])
                        if hierarchy:
                            self.vbuf[index + j].limb = matrix[len(matrix) - 1]
                            if self.vbuf[index + j].limb:
                                self.vbuf[index + j].pos += self.vbuf[index + j].limb.pos
            elif data[i] == 0x02:
                try:
                    index = ((data[i + 2] & 0x0F) << 3) | (data[i + 3] >> 1)
                    if data[i + 1] == 0x10:
                        # TODO: This pattern appears frequently. Make a function for it.
                        self.vbuf[index].normal = Vector(unpack_from("bbb", data, i + 4)).xzy
                        self.vbuf[index].normal.y = -self.vbuf[index].normal.y
                        self.vbuf[index].normal /= 128
                        # FIXME: BBBB pattern and [0]? This must be a mistake. Investigate further.
                        self.vbuf[index].color = unpack_from("BBBB", data, i + 4)[0] / 255
                    elif data[i + 1] == 0x14:
                        self.vbuf[index].uv = Vector(unpack_from(">hh", data, i + 4))
                except IndexError:
                    if not extraLenient:
                        log.exception(f"Bad vertex indices in 0x02 at 0x{i:X} {w0:08X} {w1:08X}")
            elif data[i] == 0x05 or data[i] == 0x06:
                if has_tex:
                    material = None
                    for j in range(len(self.material)):
                        if self.material[j].name == f"mtl_{self.tile[0].data:08X}":
                            material = self.material[j]
                            break
                    if material == None:
                        material = self.tile[0].create(
                            self.segment, 
                            self.use_transparency,
                            self.config["replicate_tex_mirror_blender"],
                            self.config["enable_tex_mirror_sharp_ocarina_tags"],
                            self.config["enable_tex_clamp_sharp_ocarina_tags"],
                            self.config["enable_tex_clamp_blender"],
                            self.config["export_textures"],
                            self.config["fpath"],
                            prefix=self.prefix
                        )
                        if material:
                            self.material.append(material)
                    has_tex = False
                v1, v2 = None, None
                vi1, vi2 = -1, -1
                if not self.config["import_textures"]:
                    material = None
                nbefore_props = ["verts","uvs","colors","vgroups","faces","faces_use_smooth","normals"]
                nbefore_lengths = [(nbefore_prop, len(getattr(mesh, nbefore_prop))) for nbefore_prop in nbefore_props]
                # a1 a2 a3 are microcode values
                def addTri(a1, a2, a3):
                    try:
                        verts = [self.vbuf[a >> 1] for a in (a1,a2,a3)]
                    except IndexError:
                        if extraLenient:
                            return False
                        raise
                    verts_pos = [(v.pos.x, v.pos.y, v.pos.z) for v in verts]
                    verts_index = [mesh.verts.index(pos) if pos in mesh.verts else None for pos in verts_pos]
                    for j in range(3):
                        if verts_index[j] is None:
                            mesh.verts.append(verts_pos[j])
                            verts_index[j] = len(mesh.verts) - 1
                    mesh.uvs.append(material)
                    face_normals = []
                    for j in range(3):
                        v = verts[j]
                        vi = verts_index[j]
                        # TODO: is this computation of shadeColor correct?
                        sc = (((v.normal.x + v.normal.y + v.normal.z) / 3) + 1.0) / 2
                        self.vertexColor = Vector([v.color[0], v.color[1], v.color[2], v.color[3]])
                        self.shadeColor = Vector([sc, sc, sc])
                        mesh.colors.append(self.getCombinerColor())
                        mesh.uvs.append((self.tile[0].offset.x + v.uv.x * self.tile[0].ratio.x, self.tile[0].offset.y - v.uv.y * self.tile[0].ratio.y))
                        if hierarchy:
                            if v.limb:
                                limb_name = f"limb_{v.limb.index:02}"
                                if not (limb_name in mesh.vgroups):
                                    mesh.vgroups[limb_name] = []
                                mesh.vgroups[limb_name].append(vi)
                        face_normals.append((vi, (v.normal.x, v.normal.y, v.normal.z)))
                    mesh.faces.append(tuple(verts_index))
                    mesh.faces_use_smooth.append("G_SHADE" in self.geometryModeFlags and "G_SHADING_SMOOTH" in self.geometryModeFlags)
                    mesh.normals.append(tuple(face_normals))
                    if len(set(verts_index)) < 3 and not extraLenient:
                        log.warning(f"Found empty tri! {verts_index}")
                    return True

                try:
                    revert = not addTri(data[i+1], data[i+2], data[i+3])
                    if data[i] == 0x06:
                        revert = revert or not addTri(data[i+4+1], data[i+4+2], data[i+4+3])
                except:
                    log.exception(f"Failed to import vertices and/or their data from 0x{i:X}")
                    revert = True
                if revert:
                    # revert any change
                    for nbefore_prop, nbefore in nbefore_lengths:
                        val_prop = getattr(mesh, nbefore_prop)
                        while len(val_prop) > nbefore:
                            val_prop.pop()
            # G_TEXTURE
            elif data[i] == 0xD7:
                log.debug("0xD7 G_TEXTURE used, but unimplemented")
                # FIXME: ?
#                for _ in range(2):
#                    if ((w1 >> 16) & 0xFFFF) < 0xFFFF:
#                        self.tile[i].scale.x = ((w1 >> 16) & 0xFFFF) * 0.0000152587891
#                    else:
#                        self.tile[i].scale.x = 1.0
#                    if (w1 & 0xFFFF) < 0xFFFF:
#                        self.tile[i].scale.y = (w1 & 0xFFFF) * 0.0000152587891
#                    else:
#                        self.tile[i].scale.y = 1.0
                pass
            # G_POPMTX
            elif data[i] == 0xD8 and self.config["enable_matrices"]:
                if hierarchy and len(matrix) > 1:
                    matrix.pop()
            # G_MTX
            elif data[i] == 0xDA and self.config["enable_matrices"]:
                log.debug("0xDA G_MTX used, but implementation may be faulty")
                # FIXME: this looks super weird, not sure what it's doing either
                if hierarchy and data[i + 4] == 0x0D:
                    if (data[i + 3] & 0x04) == 0:
                        matrixLimb = hierarchy.getMatrixLimb(unpack_from(">L", data, i + 4)[0])
                        if (data[i + 3] & 0x02) == 0:
                            newMatrixLimb = Limb()
                            newMatrixLimb.index = matrixLimb.index
                            newMatrixLimb.pos = (Vector([matrixLimb.pos.x, matrixLimb.pos.y, matrixLimb.pos.z]) + matrix[len(matrix) - 1].pos) / 2
                            matrixLimb = newMatrixLimb
                        if (data[i + 3] & 0x01) == 0:
                            matrix.append(matrixLimb)
                        else:
                            matrix[len(matrix) - 1] = matrixLimb
                    else:
                        matrix.append(matrix[len(matrix) - 1])
                elif hierarchy:
                    log.error(f"unknown limb {w0:08X} {w1:08X}")
            # G_DL
            elif data[i] == 0xDE:
                log.trace(f"G_DE at 0x{segmentMask | i:X} {w0:08X}{w1:08X}")
                #mesh.create(mesh_name_format, hierarchy, offset, self.checkUseNormals())
                #mesh.__init__()
                #offset = segmentMask | i
                if validOffset(self.segment, w1):
                    buildRec(w1)
                if data[i + 1] != 0x00:
                    mesh.create(mesh_name_format, hierarchy, offset, self.checkUseNormals(), prefix=self.prefix)
                    self.alreadyRead[segment].append((startOffset,i))
                    return
            # G_ENDDL
            elif data[i] == 0xDF:
                log.trace(f"G_ENDDL at 0x{segmentMask | i:X} {w0:08X}{w1:08X}")
                mesh.create(mesh_name_format, hierarchy, offset, self.checkUseNormals(), prefix=self.prefix)
                self.alreadyRead[segment].append((startOffset,i))
                return
            # handle "LOD dlists"
            elif data[i] == 0xE1:
                # 4 bytes starting at data[i+8+4] is a distance to check for displaying this dlist
                #mesh.create(mesh_name_format, hierarchy, offset, self.checkUseNormals())
                #mesh.__init__()
                #offset = segmentMask | i
                if validOffset(self.segment, w1):
                    buildRec(w1)
                else:
                    log.warning(f"Invalid 0xE1 offset 0x{w1:04X}, skipping")
            # G_RDPPIPESYNC
            elif data[i] == 0xE7:
                #mesh.create(mesh_name_format, hierarchy, offset, self.checkUseNormals())
                #mesh.__init__()
                #offset = segmentMask | i
                pass
            elif data[i] == 0xF0:
                self.palSize = ((w1 & 0x00FFF000) >> 13) + 1
            elif data[i] == 0xF2:
                self.tile[self.curTile].rect.x = (w0 & 0x00FFF000) >> 14
                self.tile[self.curTile].rect.y = (w0 & 0x00000FFF) >> 2
                self.tile[self.curTile].rect.z = (w1 & 0x00FFF000) >> 14
                self.tile[self.curTile].rect.w = (w1 & 0x00000FFF) >> 2
                self.tile[self.curTile].dims[0] = (self.tile[self.curTile].rect.z - self.tile[self.curTile].rect.x) + 1
                self.tile[self.curTile].dims[1] = (self.tile[self.curTile].rect.w - self.tile[self.curTile].rect.y) + 1
                self.tile[self.curTile].texBytes = int(self.tile[self.curTile].dims[0] * self.tile[self.curTile].dims[1]) << 1
                if (self.tile[self.curTile].texBytes >> 16) == 0xFFFF:
                    self.tile[self.curTile].texBytes = self.tile[self.curTile].size << 16 >> 15
                self.tile[self.curTile].calculateSize(self.config["replicate_tex_mirror_blender"])
            # G_LOADTILE, G_TEXRECT, G_SETZIMG, G_SETCIMG (2d "direct" drawing?)
            elif data[i] in (0xF4, 0xE4, 0xFE, 0xFF):
                log.debug(f"0x{data[i]:X} {w0:08X} : {w1:08X}")
            # G_SETTILE
            elif data[i] == 0xF5:
                self.tile[self.curTile].texFmt = (w0 >> 21) & 0b111
                self.tile[self.curTile].texSiz = (w0 >> 19) & 0b11
                self.tile[self.curTile].lineSize = (w0 >> 9) & 0x1FF
                clamp_mirror = [(w1 >> 8) & 0x03, (w1 >> 18) & 0x03]
                self.tile[self.curTile].mirror = [b & 1 != 0 for b in clamp_mirror]
                self.tile[self.curTile].wrap = [b & 2 == 0 for b in clamp_mirror]
                self.tile[self.curTile].mask.x = (w1 >> 4) & 0x0F
                self.tile[self.curTile].mask.y = (w1 >> 14) & 0x0F
                self.tile[self.curTile].tshift.x = w1 & 0x0F
                self.tile[self.curTile].tshift.y = (w1 >> 10) & 0x0F
            elif data[i] == 0xFA:
                self.primColor = Vector([((w1 >> (8*(3-i))) & 0xFF) / 255 for i in range(4)])
                log.debug(f"new primColor -> {self.primColor!r}")
                #self.primColor = Vector([min(((w1 >> 24) & 0xFF) / 255, 1.0), min(0.003922 * ((w1 >> 16) & 0xFF), 1.0), min(0.003922 * ((w1 >> 8) & 0xFF), 1.0), min(0.003922 * ((w1) & 0xFF), 1.0)])
            elif data[i] == 0xFB:
                self.envColor = Vector([((w1 >> (8*(3-i))) & 0xFF) / 255 for i in range(4)])
                log.debug(f"new envColor -> {self.envColor!r}")
                #self.envColor = Vector([min(0.003922 * ((w1 >> 24) & 0xFF), 1.0), min(0.003922 * ((w1 >> 16) & 0xFF), 1.0), min(0.003922 * ((w1 >> 8) & 0xFF), 1.0)])
                if self.config["invert_env_color"]:
                    self.envColor = Vector([1 - c for c in self.envColor])
            elif data[i] == 0xFD:
                try:
                    if data[i - 8] == 0xF2:
                        self.curTile = 1
                    else:
                        self.curTile = 0
                except:
                    log.exception(f"Failed to switch texel? at 0x{i:X}")
                    pass
                try:
                    if data[i + 8] == 0xE8:
                        self.tile[0].palette = w1
                    else:
                        self.tile[self.curTile].data = w1
                except:
                    log.exception(f"Failed to switch texel data? at 0x{i:X}")
                    pass
                has_tex = True
            # G_CULLDL, G_BRANCH_Z, G_SETOTHERMODE_L, G_SETOTHERMODE_H, G_RDPLOADSYNC, G_RDPTILESYNC, G_LOADBLOCK,
            elif data[i] in (0x03,0x04,0xE2,0xE3,0xE6,0xE8,0xF3,):
                # not relevant for importing
                pass
            # G_GEOMETRYMODE
            elif data[i] == 0xD9:
                # TODO: do not push mesh if geometry mode doesnt actually change?
                #mesh.create(mesh_name_format, hierarchy, offset, self.checkUseNormals())
                #mesh.__init__()
                #offset = segmentMask | i
                # https://wiki.cloudmodding.com/oot/F3DZEX#RSP_Geometry_Mode
                # TODO: SharpOcarina tags
                geometryModeMasks = {
                    "G_ZBUFFER":            0b00000000000000000000000000000001,
                    "G_SHADE":              0b00000000000000000000000000000100, # used by 0x05/0x06 for mesh.faces_use_smooth
                    "G_CULL_FRONT":         0b00000000000000000000001000000000, # TODO: set culling (not possible per-face or per-material or even per-object apparently) / SharpOcarina tags
                    "G_CULL_BACK":          0b00000000000000000000010000000000, # TODO: same
                    "G_FOG":                0b00000000000000010000000000000000,
                    "G_LIGHTING":           0b00000000000000100000000000000000,
                    "G_TEXTURE_GEN":        0b00000000000001000000000000000000, # TODO: billboarding?
                    "G_TEXTURE_GEN_LINEAR": 0b00000000000010000000000000000000, # TODO: billboarding?
                    "G_SHADING_SMOOTH":     0b00000000001000000000000000000000, # used by 0x05/0x06 for mesh.faces_use_smooth
                    "G_CLIPPING":           0b00000000100000000000000000000000,
                }
                clearbits = ~w0 & 0x00FFFFFF
                setbits = w1
                for flagName, flagMask in geometryModeMasks.items():
                    if clearbits & flagMask:
                        self.geometryModeFlags.discard(flagName)
                        clearbits = clearbits & ~flagMask
                    if setbits & flagMask:
                        self.geometryModeFlags.add(flagName)
                        setbits = setbits & ~flagMask
                log.debug(f"Geometry mode flags as of 0x{i:X}: {self.geometryModeFlags!r}")
                """
                # many unknown flags. keeping this commented out for any further research
                if clearbits:
                    log.warning(f"Unknown geometry mode flag at 0x{i:X} in clearbits {bin(clearbits)}")
                if setbits:
                    log.warning(f"Unknown geometry mode flag at 0x{i:X} in setbits {bin(setbits)}")
                """
            # G_SETCOMBINE
            elif data[i] == 0xFC:
                # https://wiki.cloudmodding.com/oot/F3DZEX/Opcode_Details#0xFC_.E2.80.94_G_SETCOMBINE
                pass # TODO:
            else:
                log.warning(f"Skipped (unimplemented) opcode 0x{data[i]:02X}")
        log.warning(f"Reached end of dlist started at 0x{startOffset:X}")
        mesh.create(mesh_name_format, hierarchy, offset, self.checkUseNormals(), prefix=self.prefix)
        self.alreadyRead[segment].append((startOffset,endOffset))

    def LinkTpose(self, hierarchy):
        log = getLogger("F3DZEX.LinkTpose")
        segment = []
        data = self.segment[0x06]
        segment = self.segment
        RX, RY, RZ = 0,0,0
        BoneCount  = hierarchy.limbCount
        bpy.context.scene.tool_settings.use_keyframe_insert_auto = True
        bonesIndx = [0,-90,0,0,0,0,0,0,0,90,0,0,0,180,0,0,-180,0,0,0,0]
        bonesIndy = [0,90,0,0,0,90,0,0,90,-90,-90,-90,0,0,0,90,0,0,90,0,0]
        bonesIndz = [0,0,0,0,0,0,0,0,0,0,0,0,0,-90,0,0,90,0,0,0,0]

        log.info("Link T Pose...")
        for i in range(BoneCount):
            bIndx = ((BoneCount-1) - i)
            if (i > -1):
                bone = hierarchy.armature.bones[f"limb_{bIndx:02}"]
                bone.select = True
                bpy.ops.transform.rotate(value = radians(bonesIndx[bIndx]), constraint_axis=(True, False, False))
                bpy.ops.transform.rotate(value = radians(bonesIndz[bIndx]), constraint_axis=(False, False, True))
                bpy.ops.transform.rotate(value = radians(bonesIndy[bIndx]), constraint_axis=(False, True, False))
                bpy.ops.pose.select_all(action="DESELECT")

        hierarchy.armature.bones["limb_00"].select = True ## Translations
        bpy.ops.transform.translate(value =(0, 0, 0), constraint_axis=(True, False, False))
        bpy.ops.transform.translate(value = (0, 0, 50), constraint_axis=(False, False, True))
        bpy.ops.transform.translate(value = (0, 0, 0), constraint_axis=(False, True, False))
        bpy.ops.pose.select_all(action="DESELECT")
        bpy.context.scene.tool_settings.use_keyframe_insert_auto = False

        for i in range(BoneCount):
            bIndx = i
            if (i > -1):
                bone = hierarchy.armature.bones[f"limb_{bIndx:02}"]
                bone.select = True
                bpy.ops.transform.rotate(value = radians(-bonesIndy[bIndx]), constraint_axis=(False, True, False))
                bpy.ops.transform.rotate(value = radians(-bonesIndz[bIndx]), constraint_axis=(False, False, True))
                bpy.ops.transform.rotate(value = radians(-bonesIndx[bIndx]), constraint_axis=(True, False, False))
                bpy.ops.pose.select_all(action="DESELECT")

        hierarchy.armature.bones["limb_00"].select = True ## Translations
        bpy.ops.transform.translate(value =(0, 0, 0), constraint_axis=(True, False, False))
        bpy.ops.transform.translate(value = (0, 0, -50), constraint_axis=(False, False, True))
        bpy.ops.transform.translate(value = (0, 0, 0), constraint_axis=(False, True, False))
        bpy.ops.pose.select_all(action="DESELECT")

    def buildLinkAnimations(self, hierarchy, anim_to_play):
        log = getLogger("F3DZEX.buildLinkAnimations")
        # TODO: buildLinkAnimations hasn't been rewritten/improved like buildAnimation has
        log.warning("The code to build link animations has not been improved/tested for a while, not sure what features it lacks compared to regular animations, pretty sure it will not import all animations")
        segment = self.segment
        n_anims = self.animTotal

        if (anim_to_play > 0 and anim_to_play <= n_anims):
            currentanim = anim_to_play - 1
        else:
            currentanim = 0

        AnimationOffset = self.offsetAnims[currentanim]
        seg, offset = splitOffset(hierarchy.offset)
        BoneCount  = hierarchy.limbCount
        armature = hierarchy.armature
        AniSeg = AnimationOffset >> 24
        AnimationOffset &= 0xFFFFFF
        frameTotal = self.animFrames[currentanim]

        BoneListListOffset = unpack_from(">L", segment[seg], offset)[0]
        BoneListListOffset &= 0xFFFFFF

        BoneOffset = unpack_from(">L", segment[seg], BoneListListOffset + (0 << 2))[0]
        S_Seg = (BoneOffset >> 24) & 0xFF
        BoneOffset &= 0xFFFFFF

        for frame in range(frameTotal):
            log.info(f"currentanim: {currentanim+1} frameCurrent: {frame+1}", currentanim+1, frame+1)
            rot_offset = AnimationOffset
            rot_offset += (frame * (BoneCount * 6 + 8))
            rot_offset += BoneCount * 6

            Trot_offset = AnimationOffset & 0xFFFFFF
            Trot_offset += (frame * (BoneCount * 6 + 8))
            translation = Vector((x + y) / 79.0 for x, y in zip(
                unpack_from(">hhh", segment[AniSeg], Trot_offset),
                unpack_from(">hhh", segment[S_Seg], BoneOffset)
            ))

            translation.z -= 25.5 

            for bIndx in reversed(range(BoneCount)): # Had to reverse here, cuz didn't find a way to rotate bones on LOCAL space, start rotating from last to first bone on hierarchy GLOBAL.
                r = Vector(unpack_from(">hhh", segment[AniSeg], rot_offset))
                rot_offset -= 6

                r /= 182.04444444444444444444 # = 0x10000 / 360

                r = Vector(radians(v) for v in r)

                log.trace(f"limb: {bIndx} RX {int(r.x)} RZ {int(r.z)} RY {int(r.y)} anim: {currentanim+1} frame: {frame+1}")
                poseBone = armature.pose.bones[f"limb_{bIndx:02}"]
                poseBone.bone.select = True
                bpy.ops.transform.rotate(value = -r.x, orient_axis="X")
                bpy.ops.transform.rotate(value = -r.z, orient_axis="Z")
                bpy.ops.transform.rotate(value = -r.y, orient_axis="Y")
                poseBone.keyframe_insert(data_path="rotation_quaternion", frame=frame+1)
                bpy.ops.pose.select_all(action="DESELECT")

            bone = armature.bones["limb_00"]
            bone.location += Vector((translation.xzy)) ## Translations
            bone.keyframe_insert(data_path="location", frame=frame+1)

            for bone in armature.data.bones:
                bone.select = True
            bpy.ops.pose.transforms_clear()
            bpy.ops.pose.select_all(action="DESELECT")

    def buildAnimation(self, hierarchyMostBones, anim_to_play):
        log = getLogger("F3DZEX.buildAnimation")

        segment = self.segment
        n_anims = self.animTotal

        if (anim_to_play > 0 and anim_to_play <= n_anims):
            currentanim = anim_to_play - 1
        else:
            currentanim = 0

        AnimationOffset = self.offsetAnims[currentanim]
        #seg, offset = splitOffset(hierarchy.offset) # not used, MUST be not relevant because we use hierarchyMostBones (its armature) as placeholder
        BoneCountMax = hierarchyMostBones.limbCount
        armature = hierarchyMostBones.armature

        if not validOffset(segment, AnimationOffset):
            log.warning(f"Skipping invalid animation offset 0x{AnimationOffset:X}")
            return

        AniSeg = AnimationOffset >> 24
        AnimationOffset &= 0xFFFFFF

        Limit = unpack_from(">H", segment[AniSeg], (AnimationOffset + 12))[0] # TODO: no idea what this is
        
        frameTotal = unpack_from(">h", segment[AniSeg], (AnimationOffset))[0]
        rot_vals_addr, RotIndexoffset = unpack_from(">LL", segment[AniSeg], (AnimationOffset + 4))

        rot_vals_addr  &= 0xFFFFFF
        RotIndexoffset &= 0xFFFFFF

        rot_vals_max_length = int ((RotIndexoffset - rot_vals_addr) / 2)
        if rot_vals_max_length < 0:
            log.info("rotation indices (animation data) is located before indexed rotation values, this is weird but fine")
            rot_vals_max_length = (len(segment[AniSeg]) - rot_vals_addr) // 2
        rot_vals_cache = []
        def rot_vals(index, errorDefault=0):
            if index < 0 or (rot_vals_max_length and index >= rot_vals_max_length):
                log.trace(f"index in rotations table {index} is out of bounds (rotations table is <= {rot_vals_max_length} long)")
                return errorDefault
            if index >= len(rot_vals_cache):
                rot_vals_cache.extend(unpack_from(">h", segment[AniSeg], (rot_vals_addr) + (j * 2))[0] for j in range(len(rot_vals_cache),index+1))
                log.trace(f"Computed rot_vals_cache up to {index} {rot_vals_cache!r}")
            return rot_vals_cache[index]

        bpy.context.scene.frame_end = max(frameTotal, bpy.context.scene.frame_end)

        for frame in range(frameTotal):
            log.log(
                logging.INFO if (frame + 1) % min(20, max(min(10, frameTotal), frameTotal // 3)) == 0 else logging.DEBUG,
                f"anim: {currentanim+1}/{self.animTotal} frame: {frame+1}/{frameTotal}")

            # Translations
            translation = unpack_from(">hhh", segment[AniSeg], RotIndexoffset)
            translation = [v + frame if v >= Limit else v for v in translation]
            translation = Vector(rot_vals(v) for v in translation)
            log.trace(f"X {int(translation.x)} Y {int(translation.z)} Z {int(translation.y)}")
            translation *= self.config["scale_factor"]

            bone = armature.pose.bones["limb_00"]
            bone.location += translation
            bone.keyframe_insert(data_path="location", frame=frame+1)
            
            # Rotations
            log.trace(f"       {frameTotal} Frames {Limit} still values {(rot_vals_max_length - Limit) / frameTotal:f} tracks") # what is this debug message?
            for bIndx in reversed(range(BoneCountMax)): # Had to reverse here, cuz didn't find a way to rotate bones on LOCAL space, start rotating from last to first bone on hierarchy GLOBAL.
                if RotIndexoffset + (bIndx * 6) + 10 + 2 > len(segment[AniSeg]):
                    log.trace(f"Ignoring bone {bIndx} in animation {anim_to_play}, rotation table does not have that many entries")
                    continue

                rot_index = unpack_from(">hhh", segment[AniSeg], RotIndexoffset + (bIndx * 6) + 6)
                rot_index_limited = [v + frame if v >= Limit else v for v in rot_index]

                try:
                    r = Vector(rot_vals(v, None) for v in rot_index_limited)
                except:
                    log.trace(f"Ignoring bone {bIndx} in animation {anim_to_play}, rotation table did not have the entry")
                    continue
                
                r /= 182.04444444444444444444 # = 0x10000 / 360

                log.trace(f"limb: {bIndx} XIdx: {rot_index[0]} {rot_index_limited[0]} YIdx: {rot_index[1]} {rot_index_limited[1]} ZIdx: {rot_index[2]} {rot_index_limited[2]} frameTotal: {frameTotal}")
                log.trace(f"limb: {bIndx} RX {int(r.x)} RZ {int(r.y)} RY {int(r.z)} anim: {currentanim+1} frame: {frame+1} frameTotal: {frameTotal}")
                
                r = Vector(radians(v) for v in r)

                if (bIndx > -1):
                    poseBone = armature.pose.bones[f"limb_{bIndx:02}"]
                    # TODO: Hoping to figure out a solution that doesn't require rotation ops. Revisit this idea
                    # rotation = Quaternion()
                    # rotation.rotate(Euler((RXX, 0, 0)))
                    # rotation.rotate(Euler((0, RYY, 0)))
                    # rotation.rotate(Euler((0, 0, -RZZ)))
                    # poseBone.rotation_quaternion = rotation
                    # poseBone.rotation_quaternion = rotation
                    poseBone.bone.select = True
                    bpy.ops.transform.rotate(value = -r.x, orient_axis="X")
                    bpy.ops.transform.rotate(value = -r.y, orient_axis="Z")
                    bpy.ops.transform.rotate(value =  r.z, orient_axis="Y")
                    poseBone.keyframe_insert(data_path="rotation_quaternion", frame=frame+1)
                    bpy.ops.pose.select_all(action="DESELECT")

            for bone in armature.data.bones:
                bone.select = True
            bpy.ops.pose.transforms_clear()
            bpy.ops.pose.select_all(action="DESELECT")
        
        print(len(self.tile))
