# -*- mode: python ; coding: utf-8 -*-
# Builds dist/DeskApp/ containing two programs that share one folder:
#   DeskApp.exe        - workstation client (window only, no console)
#   DeskAppServer.exe  - Central Server (console window shows status and the first-run password)
# Build: python -m PyInstaller DeskApp.spec --noconfirm
# Nothing in the build needs internet access at runtime.

block_cipher = None

# Libraries that may be installed on the build PC but are not used by DeskApp
EXCLUDES = ['numpy', 'pandas', 'PIL', 'matplotlib', 'scipy', 'tkinter', 'IPython', 'pytest',
            'PyQt5', 'PyQt6', 'PySide2', 'bcrypt']

DATAS = [
    ('deploy/seed_heads.example.json', '.'),
    ('DEPLOYMENT.md', '.'),
    ('Launch_DeskApp.bat', '.'),
    ('Launch_Server_Daemon.bat', '.'),
]

client = Analysis(['main.py'], pathex=[], binaries=[], datas=DATAS, hiddenimports=[],
                  hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=EXCLUDES,
                  cipher=block_cipher, noarchive=False)
server = Analysis(['server_main.py'], pathex=[], binaries=[], datas=[], hiddenimports=[],
                  hookspath=[], hooksconfig={}, runtime_hooks=[],
                  excludes=EXCLUDES + ['PySide6', 'shiboken6', 'qasync'],
                  cipher=block_cipher, noarchive=False)

client_pyz = PYZ(client.pure, client.zipped_data, cipher=block_cipher)
server_pyz = PYZ(server.pure, server.zipped_data, cipher=block_cipher)

client_exe = EXE(client_pyz, client.scripts, [], exclude_binaries=True, name='DeskApp',
                 debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
                 console=False, disable_windowed_traceback=False)
server_exe = EXE(server_pyz, server.scripts, [], exclude_binaries=True, name='DeskAppServer',
                 debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
                 console=True, disable_windowed_traceback=False)

coll = COLLECT(client_exe, client.binaries, client.zipfiles, client.datas,
               server_exe, server.binaries, server.zipfiles, server.datas,
               strip=False, upx=False, upx_exclude=[], name='DeskApp')
