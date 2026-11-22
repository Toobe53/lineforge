# LineForge — install the packaged zip and leave the add-on enabled for the user.
# GPL-2.0-or-later.
import os
import sys
import traceback

import bpy

ZIP = r"C:\LineForge\dist\lineforge-0.2.0.zip"
ADDONS = bpy.utils.user_resource('SCRIPTS', path="addons")


def main():
    for mod in list(sys.modules):
        if mod == "lineforge" or mod.startswith("lineforge."):
            del sys.modules[mod]

    bpy.ops.preferences.addon_install(filepath=ZIP, overwrite=True)
    print("INSTALL OK")
    bpy.ops.preferences.addon_enable(module="lineforge")
    print("ENABLE OK")

    import lineforge
    from lineforge import renderer
    print("MODULE", lineforge.__file__)
    print("CORE", renderer.core().__file__)
    print("CORE_VER", renderer.core().__version__)

    bpy.ops.wm.save_userpref()
    print("USERPREF SAVED")

    installed = os.path.join(ADDONS, "lineforge")
    print("INSTALLED_AT", installed, os.path.isdir(installed))
    pyd = os.path.join(installed, "bin", "lineforge_core.pyd")
    print("PYD", pyd, os.path.getsize(pyd) if os.path.exists(pyd) else -1)
    print("INSTALL KEEP OK")


try:
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
