# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for building the MobileStore desktop application."""

from pathlib import Path

project_root = Path(SPECPATH)

a = Analysis(
    [str(project_root / "app" / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "resources"), "resources"),
        (str(project_root / "alembic.ini"), "."),
        (str(project_root / "migrations"), "migrations"),
    ],
    hiddenimports=[
        "sqlalchemy.sql.default_comparator",
        "sqlalchemy.dialects.sqlite",
        "alembic",
        "alembic.runtime.migration",
        "alembic.operations.ops",
        "logging.config",
        "PySide6.QtPrintSupport",
        "PySide6.QtWebSockets",
        "PySide6.QtNetwork",
        "PySide6.QtSvg",
        "rapidfuzz",
        "rapidfuzz.fuzz",
        "rapidfuzz.process",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff"],
    noarchive=False,
)

pyz = PYZ(a.pure)

icon_path = project_root / "resources" / "mobilestore.ico"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MobileStore",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon_path) if icon_path.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MobileStore",
)
