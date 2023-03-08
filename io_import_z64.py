import bpy, bmesh, os, struct

from bpy.props import *
from bpy_extras.image_utils import load_image
from bpy_extras.node_shader_utils import PrincipledBSDFWrapper
from math import *
from struct import pack, unpack_from

from mathutils import Vector, Matrix
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

class Tile:
    def __init__(self):
        self.current_texture_file_path = None
        self.texFmt, self.texBytes = 0x00, 0
        self.width, self.height = 0, 0
        self.rWidth, self.rHeight = 0, 0
        self.texSiz = 0
        self.lineSize = 0
        self.rect = Vector([0, 0, 0, 0])
        self.scale = Vector([1, 1])
        self.ratio = Vector([1, 1])
        self.clip = Vector([0, 0])
        self.mask = Vector([0, 0])
        self.shift = Vector([0, 0])
        self.tshift = Vector([0, 0])
        self.offset = Vector([0, 0])
        self.data = 0x00000000
        self.palette = 0x00000000

    def getFormatName(self):
        fmt = ['RGBA','YUV','CI','IA','I']
        siz = ['4','8','16','32']
        return '%s%s' % (
            fmt[self.texFmt] if self.texFmt < len(fmt) else 'UnkFmt',
            siz[self.texSiz] if self.texSiz < len(siz) else '_UnkSiz'
        )

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
            prefix=""):
        # TODO: texture files are written several times, at each usage
        log = getLogger('Tile.create')
        fmtName = self.getFormatName()
        #Noka here
        extrastring = ""
        w = self.rWidth
        if int(self.clip.x) & 1 != 0:
            if replicate_tex_mirror_blender:
                w <<= 1
            if enable_mirror_tags:
                extrastring += "#MirrorX"
        h = self.rHeight
        if int(self.clip.y) & 1 != 0:
            if replicate_tex_mirror_blender:
                h <<= 1
            if enable_mirror_tags:
                extrastring += "#MirrorY"
        if int(self.clip.x) & 2 != 0 and enable_clamp_tags:
            extrastring += "#ClampX"
        if int(self.clip.y) & 2 != 0 and enable_clamp_tags:
            extrastring += "#ClampY"
        self.current_texture_file_path = (
            '%s/textures/%s%s_%08X%s%s.tga'
            % (fpath, prefix, fmtName, self.data,
                ('_pal%08X' % self.palette) if self.texFmt == 2 else '',
                extrastring))
        if export_textures: # FIXME: exportTextures == False breaks the script
            try:
                os.mkdir(fpath + "/textures")
            except FileExistsError:
                pass
            except:
                log.exception('Could not create textures directory %s' % (fpath + "/textures"))
                pass
            if not os.path.isfile(self.current_texture_file_path):
                log.debug('Writing texture %s (format 0x%02X)' % (self.current_texture_file_path, self.texFmt))
                file = open(self.current_texture_file_path, 'wb')
                self.write_error_encountered = False
                if self.texFmt == 2:
                    if self.texSiz not in (0, 1):
                        log.error('Unknown texture format %d with pixel size %d', self.texFmt, self.texSiz)
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
                if int(self.clip.y) & 1 != 0 and replicate_tex_mirror_blender:
                    self.writeImageData(file, segment, replicate_tex_mirror_blender, True)
                else:
                    self.writeImageData(file, segment, replicate_tex_mirror_blender)
                file.close()
                if self.write_error_encountered:
                    oldName = self.current_texture_file_path
                    oldNameDir, oldNameBase = os.path.split(oldName)
                    newName = oldNameDir + '/' + prefix + 'fallback_' + oldNameBase
                    log.warning('Moving failed texture file import from %s to %s', oldName, newName)
                    if os.path.isfile(newName):
                        os.remove(newName)
                    os.rename(oldName, newName)
                    self.current_texture_file_path = newName
        try:
            # TODO: Investigate whether Texture is needed anymore
            tex_name = prefix + ('tex_%s_%08X' % (fmtName,self.data))
            # tex = bpy.data.textures.new(name=tex_name, type='IMAGE')
            img = load_image(self.current_texture_file_path)
            if img:
                # tex.image = img
                if int(self.clip.x) & 2 != 0 and enable_blender_clamp:
                    img.use_clamp_x = True
                if int(self.clip.y) & 2 != 0 and enable_blender_clamp:
                    img.use_clamp_y = True

            mtl_name = prefix + ('mtl_%08X' % self.data)
            material = bpy.data.materials.new(name=mtl_name)
            material.use_nodes = True

            bsdf = PrincipledBSDFWrapper(material, is_readonly=False)
            bsdf.base_color_texture.image = None

            if use_transparency:
                material.blend_method = "HASHED"
                links = material.node_tree.links
                links.new(
                    bsdf.base_color_texture.node_image.outputs["Alpha"],
                    bsdf.node_principled_bsdf.inputs["Alpha"]
                )
                
            return material
            
        except:
            log.exception('Failed to create material mtl_%08X %r', self.data)
            return None

    def calculateSize(self, replicate_tex_mirror_blender, enable_toon):
        log = getLogger('Tile.calculateSize')
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
            log.warning('Unknown format for texture %s texFmt %d texSiz %d', self.current_texture_file_path, self.texFmt, self.texSiz)
        lineWidth = self.lineSize << lineShift
        self.lineSize = lineWidth
        tileWidth = self.rect.z - self.rect.x + 1
        tileHeight = self.rect.w - self.rect.y + 1
        maskWidth = 1 << int(self.mask.x)
        maskHeight = 1 << int(self.mask.y)
        lineHeight = 0
        if lineWidth > 0:
            lineHeight = min(int(maxTxl / lineWidth), tileHeight)
        if self.mask.x > 0 and (maskWidth * maskHeight) <= maxTxl:
            self.width = maskWidth
        elif (tileWidth * tileHeight) <= maxTxl:
            self.width = tileWidth
        else:
            self.width = lineWidth
        if self.mask.y > 0 and (maskWidth * maskHeight) <= maxTxl:
            self.height = maskHeight
        elif (tileWidth * tileHeight) <= maxTxl:
            self.height = tileHeight
        else:
            self.height = lineHeight
        clampWidth, clampHeight = 0, 0
        if self.clip.x == 1:
            clampWidth = tileWidth
        else:
            clampWidth = self.width
        if self.clip.y == 1:
            clampHeight = tileHeight
        else:
            clampHeight = self.height
        if maskWidth > self.width:
            self.mask.x = powof(self.width)
            maskWidth = 1 << int(self.mask.x)
        if maskHeight > self.height:
            self.mask.y = powof(self.height)
            maskHeight = 1 << int(self.mask.y)
        if int(self.clip.x) & 2 != 0:
            self.rWidth = pow2(clampWidth)
        elif int(self.clip.x) & 1 != 0:
            self.rWidth = pow2(maskWidth)
        else:
            self.rWidth = pow2(self.width)
        if int(self.clip.y) & 2 != 0:
            self.rHeight = pow2(clampHeight)
        elif int(self.clip.y) & 1 != 0:
            self.rHeight = pow2(maskHeight)
        else:
            self.rHeight = pow2(self.height)
        self.shift.x, self.shift.y = 1.0, 1.0
        if self.tshift.x > 10:
            self.shift.x = 1 << int(16 - self.tshift.x)
        elif self.tshift.x > 0:
            self.shift.x /= 1 << int(self.tshift.x)
        if self.tshift.y > 10:
            self.shift.y = 1 << int(16 - self.tshift.y)
        elif self.tshift.y > 0:
            self.shift.y /= 1 << int(self.tshift.y)
        self.ratio.x = (self.scale.x * self.shift.x) / self.rWidth
        if not enable_toon:
            self.ratio.x /= 32;
        if int(self.clip.x) & 1 != 0 and replicate_tex_mirror_blender:
            self.ratio.x /= 2
        self.offset.x = self.rect.x
        self.ratio.y = (self.scale.y * self.shift.y) / self.rHeight
        if not enable_toon:
            self.ratio.y /= 32;
        if int(self.clip.y) & 1 != 0 and replicate_tex_mirror_blender:
            self.ratio.y /= 2
        self.offset.y = 1.0 + self.rect.y

    def writePalette(self, file, segment, palSize):
        log = getLogger('Tile.writePalette')
        if not validOffset(segment, self.palette + palSize * 2 - 1):
            log.error('Segment offsets 0x%X-0x%X are invalid, writing black palette to %s (has the segment data been loaded?)' % (self.palette, self.palette + palSize * 2 - 1, self.current_texture_file_path))
            for i in range(palSize):
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
        log = getLogger('Tile.writeImageData')
        if fy == True:
            dir = (0, self.rHeight, 1)
        else:
            dir = (self.rHeight - 1, -1, -1)
        if self.texSiz <= 3:
            bpp = (0.5,1,2,4)[self.texSiz] # bytes (not bits) per pixel
        else:
            log.warning('Unknown texSiz %d for texture %s, defaulting to 4 bytes per pixel' % (self.texSiz, self.current_texture_file_path))
            bpp = 4
        lineSize = self.rWidth * bpp
        writeFallbackData = False
        if not validOffset(segment, self.data + int(self.rHeight * lineSize) - 1):
            log.error('Segment offsets 0x%X-0x%X are invalid, writing default fallback colors to %s (has the segment data been loaded?)' % (self.data, self.data + int(self.rHeight * lineSize) - 1, self.current_texture_file_path))
            writeFallbackData = True
        if (self.texFmt,self.texSiz) not in (
            (0,2), (0,3), # RGBA16, RGBA32
            #(1,-1), # YUV ? "not used in z64 games"
            (2,0), (2,1), # CI4, CI8
            (3,0), (3,1), (3,2), # IA4, IA8, IA16
            (4,0), (4,1), # I4, I8
        ):
            log.error('Unknown fmt/siz combination %d/%d (%s?)', self.texFmt, self.texSiz, self.getFormatName())
            writeFallbackData = True
        if writeFallbackData:
            size = self.rWidth * self.rHeight
            if int(self.clip.x) & 1 != 0 and replicate_tex_mirror_blender:
                size *= 2
            if int(self.clip.y) & 1 != 0 and replicate_tex_mirror_blender:
                size *= 2
            for i in range(size):
                if self.texFmt == 2: # CI (paletted)
                    file.write(pack("B", 0))
                else:
                    file.write(pack(">L", 0x000000FF))
            self.write_error_encountered = True
            return
        seg, offset = splitOffset(self.data)
        for i in range(dir[0], dir[1], dir[2]):
            off = offset + int(i * lineSize)
            line = []
            j = 0
            while j < int(self.rWidth * bpp):
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
                    log.error('Unknown format texFmt %d texSiz %d', self.texFmt, self.texSiz)
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
            if int(self.clip.x) & 1 != 0 and replicate_tex_mirror_blender:
                line.reverse()
                if self.texFmt == 2: # CI # in (0x40, 0x48, 0x50):
                    file.write(pack("B" * len(line), *line))
                else:
                    file.write(pack(">" + "L" * len(line), *line))
        if int(self.clip.y) & 1 != 0 and df == False and replicate_tex_mirror_blender:
            if fy == True:
                self.writeImageData(file, segment, False, True)
            else:
                self.writeImageData(file, segment, True, True)


class Vertex:
    def __init__(self):
        self.pos = Vector([0, 0, 0])
        self.uv = Vector([0, 0])
        self.normal = Vector([0, 0, 0])
        self.color = [0, 0, 0, 0]
        self.limb = None

    def read(self, segment, offset, scale_factor):
        log = getLogger('Vertex.read')
        if not validOffset(segment, offset + 16):
            log.warning('Invalid segmented offset 0x%X for vertex' % (offset + 16))
            return
        seg, offset = splitOffset(offset)
        self.pos.x = unpack_from(">h", segment[seg], offset)[0]
        self.pos.z = unpack_from(">h", segment[seg], offset + 2)[0]
        self.pos.y = -unpack_from(">h", segment[seg], offset + 4)[0]
        self.pos *= scale_factor
        self.uv.x = float(unpack_from(">h", segment[seg], offset + 8)[0])
        self.uv.y = float(unpack_from(">h", segment[seg], offset + 10)[0])
        self.normal.x = unpack_from("b", segment[seg], offset + 12)[0] / 128
        self.normal.z = unpack_from("b", segment[seg], offset + 13)[0] / 128
        self.normal.y = -unpack_from("b", segment[seg], offset + 14)[0] / 128
        self.color[0] = min(segment[seg][offset + 12] / 255, 1.0)
        self.color[1] = min(segment[seg][offset + 13] / 255, 1.0)
        self.color[2] = min(segment[seg][offset + 14] / 255, 1.0)
        self.color[3] = min(segment[seg][offset + 15] / 255, 1.0)


class Mesh:
    def __init__(self):
        self.verts, self.uvs, self.colors, self.faces = [], [], [], []
        self.faces_use_smooth = []
        self.vgroups = {}
        # import normals
        self.normals = []

    def create(self, name_format, hierarchy, offset, use_normals, prefix=""):
        log = getLogger('Mesh.create')
        if len(self.faces) == 0:
            log.trace('Skipping empty mesh %08X', offset)
            if self.verts:
                log.warning('Discarding unused vertices, no faces')
            return
        log.trace('Creating mesh %08X', offset)

        me_name = prefix + (name_format % ('me_%08X' % offset))
        me = bpy.data.meshes.new(me_name)
        ob = bpy.data.objects.new(prefix + (name_format % ('ob_%08X' % offset)), me)
        bpy.context.scene.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        bm = bmesh.new()
        
        for vert in self.verts:
            bm.verts.new(vert)

        color_sets = [self.colors[x:x+3] for x in range(0, len(self.colors), 3)]
        uv_sets = [self.uvs[x:x+4] for x in range(0, len(self.uvs), 4)]
        color_layer = bm.loops.layers.color.new("Col")
        uv_layer = bm.loops.layers.uv.new("UVMap")

        for face, smooth, color_set, uv_set in zip(self.faces, self.faces_use_smooth, color_sets, uv_sets):
            verts = [x for x in bm.verts]
            new_face = bm.faces.new([verts[x] for x in face])
            new_face.smooth = smooth

            # TODO: Figure out what this material nonsense is
            material = uv_set[0]
            if material:
                if material.name not in me.materials:
                    me.materials.append(material)
                # material.node_tree.nodes.get("Image Texture").image = 

                # uvd_uv.image = material.texture_slots[0].texture.image

            for loop, color, uv in zip(new_face.loops, color_set, uv_set[1:]):
                loop[color_layer] = color
                loop[uv_layer].uv = uv

        bm.to_mesh(me)
        bm.free()

        me.calc_normals()
        me.validate()
        me.update()

        log.debug('me =\n%r', me)
        log.debug('verts =\n%r', self.verts)
        log.debug('faces =\n%r', self.faces)
        log.debug('normals =\n%r', self.normals)

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
                log.exception('normals_split_custom_set failed, known issue due to duplicate faces')

        if hierarchy:
            for name, vgroup in self.vgroups.items():
                grp = ob.vertex_groups.new(name=name)
                for v in vgroup:
                    grp.add([v], 1.0, 'REPLACE')
            ob.parent = hierarchy.armature
            mod = ob.modifiers.new(hierarchy.name, 'ARMATURE')
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

        self.pos.x = unpack_from(">h", segment[seg], offset)[0]
        self.pos.z = unpack_from(">h", segment[seg], offset + 2)[0]
        self.pos.y = -unpack_from(">h", segment[seg], offset + 4)[0]
        self.pos *= scale_factor
        self.child = unpack_from("b", segment[seg], offset + 6)[0]
        self.sibling = unpack_from("b", segment[seg], offset + 7)[0]
        self.near = unpack_from(">L", segment[seg], offset + 8)[0]
        self.far = unpack_from(">L", segment[seg], offset + 12)[0]

        self.poseLoc.x = unpack_from(">h", segment[seg], rot_offset)[0]
        self.poseLoc.z = unpack_from(">h", segment[seg], rot_offset + 2)[0]
        self.poseLoc.y = unpack_from(">h", segment[seg], rot_offset + 4)[0]
        getLogger('Limb.read').trace("      Limb %r: %f,%f,%f", actuallimb, self.poseLoc.x, self.poseLoc.z, self.poseLoc.y)

class Hierarchy:
    def __init__(self):
        self.name, self.offset = "", 0x00000000
        self.limbCount, self.dlistCount = 0x00, 0x00
        self.limb = []
        self.armature = None

    def read(self, segment, offset, scale_factor, prefix=""):
        log = getLogger('Hierarchy.read')
        self.dlistCount = None
        if not validOffset(segment, offset + 5):
            log.error('Invalid segmented offset 0x%X for hierarchy' % (offset + 5))
            return False
        if not validOffset(segment, offset + 9):
            log.warning('Invalid segmented offset 0x%X for hierarchy (incomplete header), still trying to import ignoring dlistCount' % (offset + 9))
            self.dlistCount = 1
        self.name = prefix + ("sk_%08X" % offset)
        self.offset = offset
        seg, offset = splitOffset(offset)
        limbIndex_offset = unpack_from(">L", segment[seg], offset)[0]
        if not validOffset(segment, limbIndex_offset):
            log.error("        ERROR:  Limb index table 0x%08X out of range" % limbIndex_offset)
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
                log.error("        ERROR:  Limb 0x%02X offset 0x%08X out of range" % (i, limb_offset))[0]
        self.limb[0].pos = Vector([0, 0, 0])
        self.initLimbs(0x00)
        return True

    def create(self):
        rx, ry, rz = 90,0,0
        if (bpy.context.active_object):
            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        for i in bpy.context.selected_objects:
            i.select_set(False)
        self.armature = bpy.data.objects.new(self.name, bpy.data.armatures.new("%s_armature" % self.name))
        self.armature.show_in_front = True
        self.armature.data.display_type = 'STICK'
        bpy.context.scene.collection.objects.link(self.armature)
        bpy.context.view_layer.objects.active = self.armature
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)
        for i in range(self.limbCount):
            bone = self.armature.data.edit_bones.new("limb_%02i" % i)
            bone.use_deform = True
            bone.head = self.limb[i].pos

        for i in range(self.limbCount):
            bone = self.armature.data.edit_bones["limb_%02i" % i]
            if (self.limb[i].parent != -1):
                bone.parent = self.armature.data.edit_bones["limb_%02i" % self.limb[i].parent]
                bone.use_connect = False
            bone.tail = bone.head + Vector([0, 0, 0.0001])
        bpy.ops.object.mode_set(mode='OBJECT')

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
        self.segment, self.vbuf, self.tile  = [], [], []
        self.geometryModeFlags = set()

        self.animTotal = 0
        self.anim_to_play = 1 if self.config["load_animations"] else 0
        self.TimeLine = 0
        self.TimeLinePosition = 0
        self.displaylists = []

        for i in range(16):
            self.alreadyRead.append([])
            self.segment.append([])
            self.vbuf.append(Vertex())
        for i in range(2):
            self.tile.append(Tile())
            pass#self.vbuf.append(Vertex())
        for i in range(14 + 32):
            pass#self.vbuf.append(Vertex())
        while len(self.vbuf) < 32:
            self.vbuf.append(Vertex())
        self.curTile = 0
        self.material = []
        self.hierarchy = []
        self.resetCombiner()

    def loaddisplaylists(self, path):
        log = getLogger('F3DZEX.loaddisplaylists')
        if not os.path.isfile(path):
            log.info('Did not find %s (use to manually set offsets of display lists to import)', path)
            self.displaylists = []
            return
        try:
            file = open(path)
            self.displaylists = file.readlines()
            file.close()
            log.info("Loaded the display list list successfully!")
        except:
            log.exception('Could not read displaylists.txt')

    def loadSegment(self, seg, path):
        try:
            file = open(path, 'rb')
            self.segment[seg] = file.read()
            file.close()
        except:
            getLogger('F3DZEX.loadSegment').error('Could not load segment 0x%02X data from %s' % (seg, path))
            pass

    def locateHierarchies(self):
        log = getLogger('F3DZEX.locateHierarchies')
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
                            log.info("    hierarchy found at 0x%08X", j)
                            h = Hierarchy()
                            if h.read(self.segment, j, self.config["scale_factor"], prefix=self.prefix):
                                self.hierarchy.append(h)
                            else:
                                log.warning('Skipping hierarchy at 0x%08X', j)

    def locateAnimations(self):
        log = getLogger('F3DZEX.locateAnimations')
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
                log.info("          Anims found at %08X Frames: %d", i, data[i+1] & 0x00FFFFFF)
                self.animation.append(i)
                self.offsetAnims.append(i)
                self.offsetAnims[self.animTotal] = (0x06 << 24) | i
                # FIXME: it's two bytes, not one
                self.durationAnims.append(data[i+1] & 0x00FFFFFF)
                self.animTotal += 1
        if(self.animTotal > 0):
                log.info("          Total Anims                         : %d", self.animTotal)

    def locateExternAnimations(self):
        log = getLogger('F3DZEX.locateExternAnimations')
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
                log.info("          Ext Anims found at %08X" % i, "Frames:", data[i+1] & 0x00FFFFFF)
                self.animation.append(i)
                self.offsetAnims.append(i)
                self.offsetAnims[self.animTotal] = (0x0F << 24) | i
                self.animTotal += 1
        if(self.animTotal > 0):
            log.info("        Total Anims                   :", self.animTotal)

    def locateLinkAnimations(self):
        log = getLogger('F3DZEX.locateLinkAnimations')
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
                    log.debug('- Animation #%d offset: %07X frames: %d', self.animTotal+1, self.offsetAnims[self.animTotal], self.animFrames[self.animTotal])
            else:
                for i in range(0x2310, 0x34F8, 8):
                    self.animTotal += 1
                    self.animation.append(self.animTotal)
                    self.animFrames.append(self.animTotal)
                    self.offsetAnims.append(self.animTotal)
                    self.offsetAnims[self.animTotal]     = unpack_from(">L", data, i + 4)[0]
                    self.animFrames[self.animTotal] = unpack_from(">h", data, i)[0]
                    log.debug('- Animation #%d offset: %07X frames: %d', self.animTotal+1, self.offsetAnims[self.animTotal], self.animFrames[self.animTotal])
        log.info("         Link has come to town!!!!")
        if ( (len( self.segment[0x07] ) > 0) and (self.animTotal > 0)):
            self.buildLinkAnimations(self.hierarchy[0], 0)

    def importJFIF(self, data, initPropsOffset, name_format='bg_%08X'):
        log = getLogger('F3DZEX.importJFIF')
        (   imagePtr,
            unknown, unknown2,
            background_width, background_height,
            imageFmt, imageSiz, imagePal, imageFlip
        ) = struct.unpack_from('>IIiHHBBHH', data, initPropsOffset)
        t = Tile()
        t.texFmt = imageFmt
        t.texSiz = imageSiz
        log.debug(
            'JFIF background image init properties\n'
            'imagePtr=0x%X size=%dx%d fmt=%d, siz=%d (%s) imagePal=%d imageFlip=%d',
            imagePtr, background_width, background_height,
            imageFmt, imageSiz, t.getFormatName(), imagePal, imageFlip
        )
        if imagePtr >> 24 != 0x03:
            log.error('Skipping JFIF background image, pointer 0x%08X is not in segment 0x03', imagePtr)
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
        ) = struct.unpack_from('>HHHIBHBHHBBH', data, jfifDataStart)
        badJfif = []
        if marker_begin != 0xFFD8:
            badJfif.append('Expected marker_begin=0xFFD8 instead of 0x%04X' % marker_begin)
        if marker_begin_header != 0xFFE0:
            badJfif.append('Expected marker_begin_header=0xFFE0 instead of 0x%04X' % marker_begin_header)
        if header_length != 16:
            badJfif.append('Expected header_length=16 instead of %d=0x%04X' % (header_length, header_length))
        if jfif != 0x4A464946: # JFIF
            badJfif.append('Expected jfif=0x4A464946="JFIF" instead of 0x%08X' % jfif)
        if null != 0:
            badJfif.append('Expected null=0 instead of 0x%02X' % null)
        if version != 0x0101:
            badJfif.append('Expected version=0x0101 instead of 0x%04X' % version)
        if dens != 0:
            badJfif.append('Expected dens=0 instead of %d=0x%02X' % (dens, dens))
        if densx != 1:
            badJfif.append('Expected densx=1 instead of %d=0x%04X' % (densx, densx))
        if densy != 1:
            badJfif.append('Expected densy=1 instead of %d=0x%04X' % (densy, densy))
        if thumbnail_width != 0:
            badJfif.append('Expected thumbnail_width=0 instead of %d=0x%02X' % (thumbnail_width, thumbnail_width))
        if thumbnail_height != 0:
            badJfif.append('Expected thumbnail_height=0 instead of %d=0x%02X' % (thumbnail_height, thumbnail_height))
        if marker_end_header != 0xFFDB:
            badJfif.append('Expected marker_end_header=0xFFDB instead of 0x%04X' % marker_end_header)
        if badJfif:
            log.error('Bad JFIF format for background image at 0x%X:', jfifDataStart)
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
            log.error('Did not find end marker 0xFFD9 in background image at 0x%X', jfifDataStart)
            return False
        try:
            os.mkdir(self.config["fpath"] + '/textures')
        except FileExistsError:
            pass
        except:
            log.exception('Could not create textures directory %s' % (self.config["fpath"] + '/textures'))
            pass
        jfifPath = '%s/textures/jfif_%s.jfif' % (self.config["fpath"], (name_format % jfifDataStart))
        with open(jfifPath, 'wb') as f:
            f.write(jfifData)
        log.info('Copied jfif image to %s', jfifPath)
        jfifImage = load_image(jfifPath)
        me = bpy.data.meshes.new(self.prefix + (name_format % jfifDataStart))
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
        ob.location.z = max(max(v.co.z for v in obj.data.vertices) for obj in bpy.context.scene.objects if obj.type == 'MESH')
        bpy.context.scene.collection.objects.link(ob)
        return ob

    def importMap(self):
        if self.config["import_strategy"] == 'NO_DETECTION':
            self.importMapWithHeaders()
        elif self.config["import_strategy"] == 'BRUTEFORCE':
            self.searchAndImport(3, False)
        elif self.config["import_strategy"] == 'SMART':
            self.importMapWithHeaders()
            self.searchAndImport(3, True)
        elif self.config["import_strategy"] == 'TRY_EVERYTHING':
            self.importMapWithHeaders()
            self.searchAndImport(3, False)

    def importMapWithHeaders(self):
        log = getLogger('F3DZEX.importMapWithHeaders')
        data = self.segment[0x03]
        for i in range(0, len(data), 8):
            if data[i] == 0x0A:
                mapHeaderSegment = data[i+4]
                if mapHeaderSegment != 0x03:
                    log.warning('Skipping map header located in segment 0x%02X, referenced by command at 0x%X', mapHeaderSegment, i)
                    continue
                # mesh header offset 
                mho = (data[i+5] << 16) | (data[i+6] << 8) | data[i+7]
                if not mho < len(data):
                    log.error('Mesh header offset 0x%X is past the room file size, skipping', mho)
                    continue
                type = data[mho]
                log.info("            Mesh Type: %d" % type)
                if type == 0:
                    if mho + 12 > len(data):
                        log.error('Mesh header at 0x%X of type %d extends past the room file size, skipping', mho, type)
                        continue
                    count = data[mho+1]
                    startSeg = data[mho+4]
                    start = (data[mho+5] << 16) | (data[mho+6] << 8) | data[mho+7]
                    endSeg = data[mho+8]
                    end = (data[mho+9] << 16) | (data[mho+10] << 8) | data[mho+11]
                    if startSeg != endSeg:
                        log.error('Mesh header at 0x%X of type %d has start and end in different segments 0x%02X and 0x%02X, skipping', mho, type, startSeg, endSeg)
                        continue
                    if startSeg != 0x03:
                        log.error('Skipping mesh header at 0x%X of type %d: entries are in segment 0x%02X', mho, type, startSeg)
                        continue
                    log.info('Reading %d display lists from 0x%X to 0x%X', count, start, end)
                    for j in range(start, end, 8):
                        opa = unpack_from(">L", data, j)[0]
                        if opa:
                            self.use_transparency = False
                            self.buildDisplayList(None, [None], opa, mesh_name_format='%s_opa')
                        xlu = unpack_from(">L", data, j+4)[0]
                        if xlu:
                            self.use_transparency = True
                            self.buildDisplayList(None, [None], xlu, mesh_name_format='%s_xlu')
                elif type == 1:
                    format = data[mho+1]
                    entrySeg = data[mho+4]
                    entry = (data[mho+5] << 16) | (data[mho+6] << 8) | data[mho+7]
                    if entrySeg == 0x03:
                        opa = unpack_from(">L", data, entry)[0]
                        if opa:
                            self.use_transparency = False
                            self.buildDisplayList(None, [None], opa, mesh_name_format='%s_opa')
                        xlu = unpack_from(">L", data, entry+4)[0]
                        if xlu:
                            self.use_transparency = True
                            self.buildDisplayList(None, [None], xlu, mesh_name_format='%s_xlu')
                    else:
                        log.error('Skipping mesh header at 0x%X of type %d: entry is in segment 0x%02X', mho, type, entrySeg)
                    if format == 1:
                        if not self.importJFIF(data, mho + 8):
                            log.error('Failed to import jfif background image, mesh header at 0x%X of type 1 format 1', mho)
                    elif format == 2:
                        background_count = data[mho + 8]
                        backgrounds_array = unpack_from(">L", data, mho + 0xC)[0]
                        if backgrounds_array >> 24 == 0x03:
                            backgrounds_array &= 0xFFFFFF
                            for i in range(background_count):
                                bg_record_offset = backgrounds_array + i * 0x1C
                                unk82, bgid = struct.unpack_from('>HB', data, bg_record_offset)
                                if unk82 != 0x0082:
                                    log.error('Skipping JFIF: mesh header at 0x%X type 1 format 2 background record entry #%d at 0x%X expected unk82=0x0082, not 0x%04X', mho, i, bg_record_offset, unk82)
                                    continue
                                ob = self.importJFIF(
                                    data, bg_record_offset + 4,
                                    name_format='bg_%d_%s' % (i, '%08X')
                                )
                                ob.location.y -= self.config["scale_factor"] * 100 * i
                                if not ob:
                                    log.error('Failed to import jfif background image from record entry #%d at 0x%X, mesh header at 0x%X of type 1 format 2', i, bg_record_offset, mho)
                        else:
                            log.error('Skipping mesh header at 0x%X of type 1 format 2: backgrounds_array=0x%08X is not in segment 0x03', mho, backgrounds_array)
                    else:
                        log.error('Unknown format %d for mesh type 1 in mesh header at 0x%X', format, mho)
                elif type == 2:
                    if mho + 12 > len(data):
                        log.error('Mesh header at 0x%X of type %d extends past the room file size, skipping', mho, type)
                        continue
                    count = data[mho+1]
                    startSeg = data[mho+4]
                    start = (data[mho+5] << 16) | (data[mho+6] << 8) | data[mho+7]
                    endSeg = data[mho+8]
                    end = (data[mho+9] << 16) | (data[mho+10] << 8) | data[mho+11]
                    if startSeg != endSeg:
                        log.error('Mesh header at 0x%X of type %d has start and end in different segments 0x%02X and 0x%02X, skipping', mho, type, startSeg, endSeg)
                        continue
                    if startSeg != 0x03:
                        log.error('Skipping mesh header at 0x%X of type %d: entries are in segment 0x%02X', mho, type, startSeg)
                        continue
                    log.info('Reading %d display lists from 0x%X to 0x%X', count, start, end)
                    for j in range(start, end, 16):
                        opa = unpack_from(">L", data, j+8)[0]
                        if opa:
                            self.use_transparency = False
                            self.buildDisplayList(None, [None], opa, mesh_name_format='%s_opa')
                        xlu = unpack_from(">L", data, j+12)[0]
                        if xlu:
                            self.use_transparency = True
                            self.buildDisplayList(None, [None], xlu, mesh_name_format='%s_xlu')
                else:
                    log.error('Unknown mesh type %d in mesh header at 0x%X', type, mho)
            elif (data[i] == 0x14):
                return
        log.warning('Map headers ended unexpectedly')

    def importObj(self):
        log = getLogger('F3DZEX.importObj')
        log.info("Locating hierarchies...")
        self.locateHierarchies()

        if len(self.displaylists) != 0:
            log.info('Importing display lists defined in displaylists.txt')
            for offsetStr in self.displaylists:
                while offsetStr and offsetStr[-1] in ('\r','\n'):
                    offsetStr = offsetStr[:-1]
                if offsetStr.isdecimal():
                    log.warning('Reading offset %s as hexadecimal, NOT decimal', offsetStr)
                if len(offsetStr) > 2 and offsetStr[:2] == '0x':
                    offsetStr = offsetStr[2:]
                try:
                    offset = int(offsetStr, 16)
                except ValueError:
                    log.error('Could not parse %s from displaylists.txt as hexadecimal, skipping entry', offsetStr)
                    continue
                if (offset & 0xFF000000) == 0:
                    log.info('Defaulting segment for offset 0x%X to 6', offset)
                    offset |= 0x06000000
                log.info('Importing display list 0x%08X (from displaylists.txt)', offset)
                self.buildDisplayList(None, 0, offset)

        for hierarchy in self.hierarchy:
            log.info("Building hierarchy '%s'..." % hierarchy.name)
            hierarchy.create()
            for i in range(hierarchy.limbCount):
                limb = hierarchy.limb[i]
                if limb.near != 0:
                    if validOffset(self.segment, limb.near):
                        log.info("    0x%02X : building display lists..." % i)
                        self.resetCombiner()
                        self.buildDisplayList(hierarchy, limb, limb.near)
                    else:
                        log.info("    0x%02X : out of range" % i)
                else:
                    log.info("    0x%02X : n/a" % i)
        if len(self.hierarchy) > 0:
            bpy.context.view_layer.objects.active = self.hierarchy[0].armature
            self.hierarchy[0].armature.select_set(True)
            bpy.ops.object.mode_set(mode='POSE', toggle=False)
            if (self.anim_to_play > 0):
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
                    log.info('Building animations using armature %s in %s', armature.data.name, armature.name)
                    for i in range(len(self.animation)):
                        self.anim_to_play = i + 1
                        log.info("   Loading animation %d/%d 0x%08X", self.anim_to_play, len(self.animation), self.offsetAnims[self.anim_to_play-1])
                        action = bpy.data.actions.new(self.prefix + ('anim%d_%d' % (self.anim_to_play, self.durationAnims[i])))
                        # not sure what users an action is supposed to have, or what it should be linked to
                        action.use_fake_user = True
                        armature.animation_data.action = action
                        self.buildAnimations(hierarchy, 0)
                    for h in self.hierarchy:
                        h.armature.animation_data.action = action
                    bpy.context.scene.frame_end = max(self.durationAnims)
                else:
                    self.locateLinkAnimations()
            else:
                log.info("    Load anims OFF.")

        if self.config["import_strategy"] == 'NO_DETECTION':
            pass
        elif self.config["import_strategy"] == 'BRUTEFORCE':
            self.searchAndImport(6, False)
        elif self.config["import_strategy"] == 'SMART':
            self.searchAndImport(6, True)
        elif self.config["import_strategy"] == 'TRY_EVERYTHING':
            self.searchAndImport(6, False)

    def searchAndImport(self, segment, skipAlreadyRead):
        log = getLogger('F3DZEX.searchAndImport')
        data = self.segment[segment]
        self.use_transparency = self.config["detected_display_lists_use_transparency"]
        log.info(
            'Searching for %s display lists in segment 0x%02X (materials with transparency: %s)',
            'non-read' if skipAlreadyRead else 'any', segment, 'yes' if self.use_transparency else 'no')
        log.warning('If the imported geometry is weird/wrong, consider using displaylists.txt to manually define the display lists to import!')
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
                log.debug('Found opcode 0x%X at 0x%X, building display list from 0x%X', opcode, i, validOpcodesStartIndex)
                self.buildDisplayList(
                    None, [None], (segment << 24) | validOpcodesStartIndex,
                    mesh_name_format = '%s_detect',
                    skipAlreadyRead = skipAlreadyRead,
                    extraLenient = True
                )
                validOpcodesStartIndex = None
        if validOpcodesSkipped:
            log.info('Valid opcodes %s considered invalid because unimplemented (meaning rare)', ','.join('0x%02X' % opcode for opcode in sorted(validOpcodesSkipped)))

    def resetCombiner(self):
        self.primColor = Vector([1.0, 1.0, 1.0, 1.0])
        self.envColor = Vector([1.0, 1.0, 1.0, 1.0])
        self.vertexColor = Vector([1.0, 1.0, 1.0, 1.0])
        self.shadeColor = Vector([1.0, 1.0, 1.0])

    def checkUseNormals(self):
        return self.config["vertex_mode"] == 'NORMALS' or (self.config["vertex_mode"] == 'AUTO' and 'G_LIGHTING' in self.geometryModeFlags)

    def getCombinerColor(self):
        def multiply_color(v1, v2):
            return Vector(x * y for x, y in zip(v1, v2))
        cc = Vector([1.0, 1.0, 1.0, 1.0])
        # TODO: these have an effect even if vertexMode == 'NONE' ?
        if self.config["enable_prim_color"]:
            cc = multiply_color(cc, self.primColor)
        if self.config["enable_env_color"]:
            cc = multiply_color(cc, self.envColor)
        # TODO: assume G_LIGHTING means normals if set, and colors if clear, but G_SHADE may play a role too?
        if self.config["vertex_mode"] == 'COLORS' or (self.config["vertex_mode"] == 'AUTO' and 'G_LIGHTING' not in self.geometryModeFlags):
            cc = multiply_color(cc, self.vertexColor.to_4d())
        elif self.checkUseNormals():
            cc = multiply_color(cc, self.shadeColor.to_4d())
        
        return cc

    def buildDisplayList(self, hierarchy, limb, offset, mesh_name_format='%s', skipAlreadyRead=False, extraLenient=False):
        log = getLogger('F3DZEX.buildDisplayList')
        segment = offset >> 24
        segmentMask = segment << 24
        data = self.segment[segment]

        startOffset = offset & 0x00FFFFFF
        endOffset = len(data)
        if skipAlreadyRead:
            log.trace('is 0x%X in %r ?', startOffset, self.alreadyRead[segment])
            for fromOffset,toOffset in self.alreadyRead[segment]:
                if fromOffset <= startOffset and startOffset <= toOffset:
                    log.debug('Skipping already read dlist at 0x%X', startOffset)
                    return
                if startOffset <= fromOffset:
                    if endOffset > fromOffset:
                        endOffset = fromOffset
                        log.debug('Shortening dlist to end at most at 0x%X, at which point it was read already', endOffset)
            log.trace('no it is not')

        def buildRec(offset):
            self.buildDisplayList(hierarchy, limb, offset, mesh_name_format=mesh_name_format, skipAlreadyRead=skipAlreadyRead)

        mesh = Mesh()
        has_tex = False
        material = None
        if hierarchy:
            matrix = [limb]
        else:
            matrix = [None]

        log.debug('Reading dlists from 0x%08X', segmentMask | startOffset)
        for i in range(startOffset, endOffset, 8):
            w0 = unpack_from(">L", data, i)[0]
            w1 = unpack_from(">L", data, i + 4)[0]
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
                        self.vbuf[index].normal.x = unpack_from("b", data, i + 4)[0] / 128
                        self.vbuf[index].normal.z = unpack_from("b", data, i + 5)[0] / 128
                        self.vbuf[index].normal.y = -unpack_from("b", data, i + 6)[0] / 128
                        # wtf? BBBB pattern and [0]
                        self.vbuf[index].color = unpack_from("BBBB", data, i + 4)[0] / 255
                    elif data[i + 1] == 0x14:
                        self.vbuf[index].uv.x = float(unpack_from(">h", data, i + 4)[0])
                        self.vbuf[index].uv.y = float(unpack_from(">h", data, i + 6)[0])
                except IndexError:
                    if not extraLenient:
                        log.exception('Bad vertex indices in 0x02 at 0x%X %08X %08X', i, w0, w1)
            elif data[i] == 0x05 or data[i] == 0x06:
                if has_tex:
                    material = None
                    for j in range(len(self.material)):
                        if self.material[j].name == "mtl_%08X" % self.tile[0].data:
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
                nbefore_props = ['verts','uvs','colors','vgroups','faces','faces_use_smooth','normals']
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
                                limb_name = 'limb_%02i' % v.limb.index
                                if not (limb_name in mesh.vgroups):
                                    mesh.vgroups[limb_name] = []
                                mesh.vgroups[limb_name].append(vi)
                        face_normals.append((vi, (v.normal.x, v.normal.y, v.normal.z)))
                    mesh.faces.append(tuple(verts_index))
                    mesh.faces_use_smooth.append('G_SHADE' in self.geometryModeFlags and 'G_SHADING_SMOOTH' in self.geometryModeFlags)
                    mesh.normals.append(tuple(face_normals))
                    if len(set(verts_index)) < 3 and not extraLenient:
                        log.warning('Found empty tri! %d %d %d' % tuple(verts_index))
                    return True

                try:
                    revert = not addTri(data[i+1], data[i+2], data[i+3])
                    if data[i] == 0x06:
                        revert = revert or not addTri(data[i+4+1], data[i+4+2], data[i+4+3])
                except:
                    log.exception('Failed to import vertices and/or their data from 0x%X', i)
                    revert = True
                if revert:
                    # revert any change
                    for nbefore_prop, nbefore in nbefore_lengths:
                        val_prop = getattr(mesh, nbefore_prop)
                        while len(val_prop) > nbefore:
                            val_prop.pop()
            # G_TEXTURE
            elif data[i] == 0xD7:
                log.debug('0xD7 G_TEXTURE used, but unimplemented')
                # FIXME: ?
#                for i in range(2):
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
                log.debug('0xDA G_MTX used, but implementation may be faulty')
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
                    log.error("unknown limb %08X %08X" % (w0, w1))
            # G_DL
            elif data[i] == 0xDE:
                log.trace('G_DE at 0x%X %08X%08X', segmentMask | i, w0, w1)
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
                log.trace('G_ENDDL at 0x%X %08X%08X', segmentMask | i, w0, w1)
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
                    log.warning('Invalid 0xE1 offset 0x%04X, skipping', w1)
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
                self.tile[self.curTile].width = (self.tile[self.curTile].rect.z - self.tile[self.curTile].rect.x) + 1
                self.tile[self.curTile].height = (self.tile[self.curTile].rect.w - self.tile[self.curTile].rect.y) + 1
                self.tile[self.curTile].texBytes = int(self.tile[self.curTile].width * self.tile[self.curTile].height) << 1
                if (self.tile[self.curTile].texBytes >> 16) == 0xFFFF:
                    self.tile[self.curTile].texBytes = self.tile[self.curTile].size << 16 >> 15
                self.tile[self.curTile].calculateSize(self.config["replicate_tex_mirror_blender"], self.config["enable_toon"])
            # G_LOADTILE, G_TEXRECT, G_SETZIMG, G_SETCIMG (2d "direct" drawing?)
            elif data[i] == 0xF4 or data[i] == 0xE4 or data[i] == 0xFE or data[i] == 0xFF:
                log.debug('0x%X %08X : %08X', data[i], w0, w1)
            # G_SETTILE
            elif data[i] == 0xF5:
                self.tile[self.curTile].texFmt = (w0 >> 21) & 0b111
                self.tile[self.curTile].texSiz = (w0 >> 19) & 0b11
                self.tile[self.curTile].lineSize = (w0 >> 9) & 0x1FF
                self.tile[self.curTile].clip.x = (w1 >> 8) & 0x03
                self.tile[self.curTile].clip.y = (w1 >> 18) & 0x03
                self.tile[self.curTile].mask.x = (w1 >> 4) & 0x0F
                self.tile[self.curTile].mask.y = (w1 >> 14) & 0x0F
                self.tile[self.curTile].tshift.x = w1 & 0x0F
                self.tile[self.curTile].tshift.y = (w1 >> 10) & 0x0F
            elif data[i] == 0xFA:
                self.primColor = Vector([((w1 >> (8*(3-i))) & 0xFF) / 255 for i in range(4)])
                log.debug('new primColor -> %r', self.primColor)
                #self.primColor = Vector([min(((w1 >> 24) & 0xFF) / 255, 1.0), min(0.003922 * ((w1 >> 16) & 0xFF), 1.0), min(0.003922 * ((w1 >> 8) & 0xFF), 1.0), min(0.003922 * ((w1) & 0xFF), 1.0)])
            elif data[i] == 0xFB:
                self.envColor = Vector([((w1 >> (8*(3-i))) & 0xFF) / 255 for i in range(4)])
                log.debug('new envColor -> %r', self.envColor)
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
                    log.exception('Failed to switch texel? at 0x%X', i)
                    pass
                try:
                    if data[i + 8] == 0xE8:
                        self.tile[0].palette = w1
                    else:
                        self.tile[self.curTile].data = w1
                except:
                    log.exception('Failed to switch texel data? at 0x%X', i)
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
                    'G_ZBUFFER':            0b00000000000000000000000000000001,
                    'G_SHADE':              0b00000000000000000000000000000100, # used by 0x05/0x06 for mesh.faces_use_smooth
                    'G_CULL_FRONT':         0b00000000000000000000001000000000, # TODO: set culling (not possible per-face or per-material or even per-object apparently) / SharpOcarina tags
                    'G_CULL_BACK':          0b00000000000000000000010000000000, # TODO: same
                    'G_FOG':                0b00000000000000010000000000000000,
                    'G_LIGHTING':           0b00000000000000100000000000000000,
                    'G_TEXTURE_GEN':        0b00000000000001000000000000000000, # TODO: billboarding?
                    'G_TEXTURE_GEN_LINEAR': 0b00000000000010000000000000000000, # TODO: billboarding?
                    'G_SHADING_SMOOTH':     0b00000000001000000000000000000000, # used by 0x05/0x06 for mesh.faces_use_smooth
                    'G_CLIPPING':           0b00000000100000000000000000000000,
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
                log.debug('Geometry mode flags as of 0x%X: %r', i, self.geometryModeFlags)
                """
                # many unknown flags. keeping this commented out for any further research
                if clearbits:
                    log.warning('Unknown geometry mode flag at 0x%X in clearbits %s', i, bin(clearbits))
                if setbits:
                    log.warning('Unknown geometry mode flag at 0x%X in setbits %s', i, bin(setbits))
                """
            # G_SETCOMBINE
            elif data[i] == 0xFC:
                # https://wiki.cloudmodding.com/oot/F3DZEX/Opcode_Details#0xFC_.E2.80.94_G_SETCOMBINE
                pass # TODO:
            else:
                log.warning('Skipped (unimplemented) opcode 0x%02X' % data[i])
        log.warning('Reached end of dlist started at 0x%X', startOffset)
        mesh.create(mesh_name_format, hierarchy, offset, self.checkUseNormals(), prefix=self.prefix)
        self.alreadyRead[segment].append((startOffset,endOffset))

    def LinkTpose(self, hierarchy):
        log = getLogger('F3DZEX.LinkTpose')
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
                bone = hierarchy.armature.bones["limb_%02i" % (bIndx)]
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
                bone = hierarchy.armature.bones["limb_%02i" % (bIndx)]
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

    def buildLinkAnimations(self, hierarchy, newframe):
        log = getLogger('F3DZEX.buildLinkAnimations')
        # TODO: buildLinkAnimations hasn't been rewritten/improved like buildAnimations has
        log.warning('The code to build link animations has not been improved/tested for a while, not sure what features it lacks compared to regular animations, pretty sure it will not import all animations')
        segment = []
        rot_indx = 0
        rot_indy = 0
        rot_indz = 0
        data = self.segment[0x06]
        segment = self.segment
        n_anims = self.animTotal
        seg, offset = splitOffset(hierarchy.offset)
        BoneCount  = hierarchy.limbCount
        RX, RY, RZ = 0,0,0
        frameCurrent = newframe

        if (self.anim_to_play > 0 and self.anim_to_play <= n_anims):
          currentanim = self.anim_to_play - 1
        else:
          currentanim = 0

        log.info("currentanim: %d frameCurrent: %d", currentanim+1, frameCurrent+1)
        AnimationOffset = self.offsetAnims[currentanim]
        TAnimationOffset = self.offsetAnims[currentanim]
        AniSeg = AnimationOffset >> 24
        AnimationOffset &= 0xFFFFFF
        rot_offset = AnimationOffset
        rot_offset += (frameCurrent * (BoneCount * 6 + 8))
        frameTotal = self.animFrames[currentanim]
        rot_offset += BoneCount * 6

        Trot_offset = TAnimationOffset & 0xFFFFFF
        Trot_offset += (frameCurrent * (BoneCount * 6 + 8))
        TRX = unpack_from(">h", segment[AniSeg], Trot_offset)[0]
        Trot_offset += 2
        TRZ = unpack_from(">h", segment[AniSeg], Trot_offset)[0]
        Trot_offset += 2
        TRY = -unpack_from(">h", segment[AniSeg], Trot_offset)[0]
        Trot_offset += 2
        BoneListListOffset = unpack_from(">L", segment[seg], offset)[0]
        BoneListListOffset &= 0xFFFFFF

        BoneOffset = unpack_from(">L", segment[seg], BoneListListOffset + (0 << 2))[0]
        S_Seg = (BoneOffset >> 24) & 0xFF
        BoneOffset &= 0xFFFFFF
        TRX += unpack_from(">h", segment[S_Seg], BoneOffset)[0]
        TRZ += unpack_from(">h", segment[S_Seg], BoneOffset + 2)[0]
        TRY += -unpack_from(">h", segment[S_Seg], BoneOffset + 4)[0]
        newLocx = TRX / 79
        newLocz = -25.5
        newLocz += TRZ / 79
        newLocy = TRY / 79

        bpy.context.scene.tool_settings.use_keyframe_insert_auto = True

        for i in range(BoneCount):
            bIndx = ((BoneCount-1) - i) # Had to reverse here, cuz didn't find a way to rotate bones on LOCAL space, start rotating from last to first bone on hierarchy GLOBAL.
            RX = unpack_from(">h", segment[AniSeg], rot_offset)[0]
            rot_offset -= 2
            RY = unpack_from(">h", segment[AniSeg], rot_offset + 4)[0]
            rot_offset -= 2
            RZ = unpack_from(">h", segment[AniSeg], rot_offset + 8)[0]
            rot_offset -= 2

            RX /= (182.04444444444444444444)
            RY /= (182.04444444444444444444)
            RZ /= (182.04444444444444444444)

            RXX = (RX)
            RYY = (-RZ)
            RZZ = (RY)

            log.trace('limb: %d RX %d RZ %d RY %d anim: %d frame: %d', bIndx, int(RXX), int(RZZ), int(RYY), currentanim+1, frameCurrent+1)
            if (i > -1):
                bone = hierarchy.armature.bones["limb_%02i" % (bIndx)]
                bone.select = True
                bpy.ops.transform.rotate(value = radians(RXX), constraint_axis=(True, False, False))
                bpy.ops.transform.rotate(value = radians(RZZ), constraint_axis=(False, False, True))
                bpy.ops.transform.rotate(value = radians(RYY), constraint_axis=(False, True, False))
                bpy.ops.pose.select_all(action="DESELECT")

        hierarchy.armature.bones["limb_00"].select = True ## Translations
        bpy.ops.transform.translate(value =(newLocx, 0, 0), constraint_axis=(True, False, False))
        bpy.ops.transform.translate(value = (0, 0, newLocz), constraint_axis=(False, False, True))
        bpy.ops.transform.translate(value = (0, newLocy, 0), constraint_axis=(False, True, False))
        bpy.ops.pose.select_all(action="DESELECT")

        if (frameCurrent < (frameTotal - 1)):## Next Frame ### Could have done some math here but... just reverse previus frame, so it just repose.
            bpy.context.scene.tool_settings.use_keyframe_insert_auto = False

            hierarchy.armature.bones["limb_00"].select = True ## Translations
            bpy.ops.transform.translate(value = (-newLocx, 0, 0), constraint_axis=(True, False, False))
            bpy.ops.transform.translate(value = (0, 0, -newLocz), constraint_axis=(False, False, True))
            bpy.ops.transform.translate(value = (0, -newLocy, 0), constraint_axis=(False, True, False))
            bpy.ops.pose.select_all(action="DESELECT")

            rot_offset = AnimationOffset
            rot_offset += (frameCurrent * (BoneCount * 6 + 8))
            rot_offset += 6
            for i in range(BoneCount):
                RX = unpack_from(">h", segment[AniSeg], rot_offset)[0]
                rot_offset += 2
                RY = unpack_from(">h", segment[AniSeg], rot_offset)[0]
                rot_offset += 2
                RZ = unpack_from(">h", segment[AniSeg], rot_offset)[0]
                rot_offset += 2

                RX /= (182.04444444444444444444)
                RY /= (182.04444444444444444444)
                RZ /= (182.04444444444444444444)

                RXX = (-RX)
                RYY = (RZ)
                RZZ = (-RY)

                log.trace("limb: %d RX %d RZ %d RY %d anim: %d frame: %d", i, int(RXX), int(RZZ), int(RYY), currentanim+1, frameCurrent+1)
                if (i > -1):
                    bone = hierarchy.armature.bones["limb_%02i" % (i)]
                    bone.select = True
                    bpy.ops.transform.rotate(value = radians(RYY), constraint_axis=(False, True, False))
                    bpy.ops.transform.rotate(value = radians(RZZ), constraint_axis=(False, False, True))
                    bpy.ops.transform.rotate(value = radians(RXX), constraint_axis=(True, False, False))
                    bpy.ops.pose.select_all(action="DESELECT")

            bpy.context.scene.frame_end += 1
            bpy.context.scene.frame_current += 1
            frameCurrent += 1
            self.buildLinkAnimations(hierarchy, frameCurrent)
        else:
            bpy.context.scene.tool_settings.use_keyframe_insert_auto = False
            bpy.context.scene.frame_current = 1

    def buildAnimations(self, hierarchyMostBones, newframe):
        log = getLogger('F3DZEX.buildAnimations')
        rot_indx = 0
        rot_indy = 0
        rot_indz = 0
        Trot_indx = 0
        Trot_indy = 0
        Trot_indz = 0
        segment = self.segment
        RX, RY, RZ = 0,0,0
        n_anims = self.animTotal
        if (self.anim_to_play > 0 and self.anim_to_play <= n_anims):
            currentanim = self.anim_to_play - 1
        else:
            currentanim = 0

        AnimationOffset = self.offsetAnims[currentanim]
        #seg, offset = splitOffset(hierarchy.offset) # not used, MUST be not relevant because we use hierarchyMostBones (its armature) as placeholder
        BoneCountMax = hierarchyMostBones.limbCount
        armature = hierarchyMostBones.armature
        frameCurrent = newframe

        if not validOffset(segment, AnimationOffset):
            log.warning('Skipping invalid animation offset 0x%X', AnimationOffset)
            return

        AniSeg = AnimationOffset >> 24
        AnimationOffset &= 0xFFFFFF

        frameTotal = unpack_from(">h", segment[AniSeg], (AnimationOffset))[0]
        rot_vals_addr = unpack_from(">L", segment[AniSeg], (AnimationOffset + 4))[0]
        RotIndexoffset = unpack_from(">L", segment[AniSeg], (AnimationOffset + 8))[0]
        Limit = unpack_from(">H", segment[AniSeg], (AnimationOffset + 12))[0] # TODO: no idea what this is

        rot_vals_addr  &= 0xFFFFFF
        RotIndexoffset &= 0xFFFFFF

        rot_vals_max_length = int ((RotIndexoffset - rot_vals_addr) / 2)
        if rot_vals_max_length < 0:
            log.info('rotation indices (animation data) is located before indexed rotation values, this is weird but fine')
            rot_vals_max_length = (len(segment[AniSeg]) - rot_vals_addr) // 2
        rot_vals_cache = []
        def rot_vals(index, errorDefault=0):
            if index < 0 or (rot_vals_max_length and index >= rot_vals_max_length):
                log.trace('index in rotations table %d is out of bounds (rotations table is <= %d long)', index, rot_vals_max_length)
                return errorDefault
            if index >= len(rot_vals_cache):
                rot_vals_cache.extend(unpack_from(">h", segment[AniSeg], (rot_vals_addr) + (j * 2))[0] for j in range(len(rot_vals_cache),index+1))
                log.trace('Computed rot_vals_cache up to %d %r', index, rot_vals_cache)
            return rot_vals_cache[index]

        bpy.context.scene.tool_settings.use_keyframe_insert_auto = True
        bpy.context.scene.frame_end = frameTotal
        bpy.context.scene.frame_current = frameCurrent + 1

        log.log(
            logging.INFO if (frameCurrent + 1) % min(20, max(min(10, frameTotal), frameTotal // 3)) == 0 else logging.DEBUG,
            "anim: %d/%d frame: %d/%d", currentanim+1, self.animTotal, frameCurrent+1, frameTotal)

        ## Translations
        Trot_indx = unpack_from(">h", segment[AniSeg], RotIndexoffset)[0]
        Trot_indy = unpack_from(">h", segment[AniSeg], RotIndexoffset + 2)[0]
        Trot_indz = unpack_from(">h", segment[AniSeg], RotIndexoffset + 4)[0]

        if (Trot_indx >= Limit):
            Trot_indx += frameCurrent
        if (Trot_indz >= Limit):
            Trot_indz += frameCurrent
        if (Trot_indy >= Limit):
            Trot_indy += frameCurrent

        TRX = rot_vals(Trot_indx)
        TRZ = rot_vals(Trot_indy)
        TRY = rot_vals(Trot_indz)

        newLocx =  TRX * self.config["scale_factor"]
        newLocz =  TRZ * self.config["scale_factor"]
        newLocy = -TRY * self.config["scale_factor"]
        log.trace("X %d Y %d Z %d", int(TRX), int(TRY), int(TRZ))

        log.trace("       %d Frames %d still values %f tracks",frameTotal, Limit, ((rot_vals_max_length - Limit) / frameTotal)) # what is this debug message?
        for i in range(BoneCountMax):
            bIndx = ((BoneCountMax-1) - i) # Had to reverse here, cuz didn't find a way to rotate bones on LOCAL space, start rotating from last to first bone on hierarchy GLOBAL.

            if RotIndexoffset + (bIndx * 6) + 10 + 2 > len(segment[AniSeg]):
                log.trace('Ignoring bone %d in animation %d, rotation table does not have that many entries', bIndx, self.anim_to_play)
                continue

            rot_indexx = unpack_from(">h", segment[AniSeg], RotIndexoffset + (bIndx * 6) + 6)[0]
            rot_indexy = unpack_from(">h", segment[AniSeg], RotIndexoffset + (bIndx * 6) + 8)[0]
            rot_indexz = unpack_from(">h", segment[AniSeg], RotIndexoffset + (bIndx * 6) + 10)[0]

            rot_indx = rot_indexx
            rot_indy = rot_indexy
            rot_indz = rot_indexz

            if (rot_indx >= Limit):
                rot_indx += frameCurrent
            if (rot_indy >= Limit):
                rot_indy += frameCurrent
            if (rot_indz >= Limit):
                rot_indz += frameCurrent

            RX = rot_vals(rot_indx, False)
            RY = rot_vals(rot_indz, False)
            RZ = rot_vals(rot_indy, False)

            if RX is False or RY is False or RZ is False:
                log.trace('Ignoring bone %d in animation %d, rotation table did not have the entry', bIndx, self.anim_to_play)
                continue

            RX /= 182.04444444444444444444 # = 0x10000 / 360
            RY /= -182.04444444444444444444
            RZ /= 182.04444444444444444444

            RXX = radians(RX)
            RYY = radians(RY)
            RZZ = radians(RZ)

            log.trace("limb: %d XIdx: %d %d YIdx: %d %d ZIdx: %d %d frameTotal: %d", bIndx, rot_indexx, rot_indx, rot_indexy, rot_indy, rot_indexz, rot_indz, frameTotal)
            log.trace("limb: %d RX %d RZ %d RY %d anim: %d frame: %d frameTotal: %d", bIndx, int(RX), int(RZ), int(RY), currentanim+1, frameCurrent+1, frameTotal)
            if (bIndx > -1):
                bone = armature.data.bones["limb_%02i" % (bIndx)]
                bone.select = True
                bpy.ops.transform.rotate(value = RXX, constraint_axis=(True, False, False))
                bpy.ops.transform.rotate(value = RZZ, constraint_axis=(False, False, True))
                bpy.ops.transform.rotate(value = RYY, constraint_axis=(False, True, False))
                bpy.ops.pose.select_all(action="DESELECT")

        bone = armature.pose.bones["limb_00"]
        bone.location += Vector((newLocx,newLocz,-newLocy))
        bone.keyframe_insert(data_path='location')

        ### Could have done some math here but... just reverse previus frame, so it just repose.
        bpy.context.scene.tool_settings.use_keyframe_insert_auto = False

        bone = armature.pose.bones["limb_00"]
        bone.location -= Vector((newLocx,newLocz,-newLocy))

        for i in range(BoneCountMax):
            bIndx = i

            if RotIndexoffset + (bIndx * 6) + 10 + 2 > len(segment[AniSeg]):
                log.trace('Ignoring bone %d in animation %d, rotation table does not have that many entries', bIndx, self.anim_to_play)
                continue

            rot_indexx = unpack_from(">h", segment[AniSeg], RotIndexoffset + (bIndx * 6) + 6)[0]
            rot_indexy = unpack_from(">h", segment[AniSeg], RotIndexoffset + (bIndx * 6) + 8)[0]
            rot_indexz = unpack_from(">h", segment[AniSeg], RotIndexoffset + (bIndx * 6) + 10)[0]

            rot_indx = rot_indexx
            rot_indy = rot_indexy
            rot_indz = rot_indexz

            if (rot_indx > Limit):
                rot_indx += frameCurrent
            if (rot_indy > Limit):
                rot_indy += frameCurrent
            if (rot_indz > Limit):
                rot_indz += frameCurrent

            RX = rot_vals(rot_indx, False)
            RY = rot_vals(rot_indz, False)
            RZ = rot_vals(rot_indy, False)

            if RX is False or RY is False or RZ is False:
                log.trace('Ignoring bone %d in animation %d, rotation table did not have the entry', bIndx, self.anim_to_play)
                continue

            RX /= -182.04444444444444444444
            RY /= 182.04444444444444444444
            RZ /= -182.04444444444444444444

            RXX = radians(RX)
            RYY = radians(RY)
            RZZ = radians(RZ)

            log.trace("limb: %d XIdx: %d %d YIdx: %d %d ZIdx: %d %d frameTotal: %d", i, rot_indexx, rot_indx, rot_indexy, rot_indy, rot_indexz, rot_indz, frameTotal)
            log.trace("limb: %d RX %d RZ %d RY %d anim: %d frame: %d frameTotal: %d", bIndx, int(RX), int(RZ), int(RY), currentanim+1, frameCurrent+1, frameTotal)
            if (bIndx > -1):
                bone = armature.data.bones["limb_%02i" % (bIndx)]
                bone.select = True
                bpy.ops.transform.rotate(value = RYY, constraint_axis=(False, True, False))
                bpy.ops.transform.rotate(value = RZZ, constraint_axis=(False, False, True))
                bpy.ops.transform.rotate(value = RXX, constraint_axis=(True, False, False))
                bpy.ops.pose.select_all(action="DESELECT")

        if (frameCurrent < (frameTotal - 1)):## Next Frame
            frameCurrent += 1
            self.buildAnimations(hierarchyMostBones, frameCurrent)
        else:
            bpy.context.scene.frame_current = 1
