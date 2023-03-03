# zelda64-import-blender
# Import models from Zelda64 files into Blender
# Copyright (C) 2013 SoulofDeity
# Copyright (C) 2020 Dragorn421
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
    "version":     (3, 0),
    "author":      "SoulofDeity",
    "blender":     (2, 80, 0),
    "location":    "File > Import-Export",
    "description": "Import Zelda64 - updated in 2020",
    "warning":     "",
    "wiki_url":    "https://github.com/Dragorn421/zelda64-import-blender",
    "tracker_url": "https://github.com/Dragorn421/zelda64-import-blender",
    "support":     'COMMUNITY',
    "category":    "Import-Export"}

"""Anim stuff: RodLima http://www.facebook.com/rod.lima.96?ref=tn_tnmn"""


# if "bpy" in locals():
#     import importlib
#     importlib.reload(log, importer)

# else:
#     from .importer import (
#         ImportZ64,
#         menu_func_import
#     )
#     from .log import (
#         register_logging,
#         unregister_logging
#     )

import bpy

from .io_import_z64 import (
    registerLogging,
    unregisterLogging,
    ImportZ64,
    menu_func_import
)

def register():
    registerLogging()
    bpy.utils.register_class(ImportZ64)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(ImportZ64)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    unregisterLogging()

if __name__ == "__main__":
    register()
