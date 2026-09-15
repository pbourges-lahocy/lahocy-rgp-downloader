# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller pour le RGP Downloader Lahocy (Phase 5).

Construit un exécutable Windows autonome (mode "onedir", recommandé pour les
applications QtWebEngine : démarrage plus rapide et plus fiable qu'un "onefile"
qui doit ré-extraire tout le runtime Chromium à chaque lancement).

Usage :
    pyinstaller LahocyRGPDownloader.spec
"""

import os

import hatanaka

block_cipher = None

_HERE = os.path.abspath(SPECPATH)
_HATANAKA_BIN = os.path.join(os.path.dirname(hatanaka.__file__), "bin")

a = Analysis(
    ["scripts/gui.py"],
    pathex=[os.path.join(_HERE, "src")],
    binaries=[],
    datas=[
        (os.path.join(_HERE, "src", "app", "ui", "assets"), "app/ui/assets"),
        (os.path.join(_HERE, "config"), "config"),
        (_HATANAKA_BIN, "hatanaka/bin"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LahocyRGPDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LahocyRGPDownloader",
)
