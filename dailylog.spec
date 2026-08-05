# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('static', 'static')],
    # pynput 键盘监听按平台动态加载后端模块，PyInstaller 无法静态发现，需显式收进
    hiddenimports=['pynput.keyboard._win32', 'pynput._util.win32'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='dailylog',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['static\\assets\\icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='dailylog',
)

