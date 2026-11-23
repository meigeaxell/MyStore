"""Сервис безопасного обновления портативной сборки MobileStore из ZIP без потери БД и бэкапов."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from app.config import PROJECT_ROOT
from app.services.backup_service import BackupService

PROTECTED_ENTRIES = {"data", "backups"}


class UpdateService:
    """Обновляет портативную версию MobileStore из нового ZIP-архива, сохраняя data/ и backups/."""

    @staticmethod
    def inspect_update_zip(zip_path: Path | str) -> tuple[bool, str, str]:
        """Проверяет, что ZIP содержит валидную сборку MobileStore.

        Возвращает (ok, message, root_prefix).
        """
        path = Path(zip_path)
        if not path.exists() or not path.is_file():
            return False, "Saýlanan ZIP faýly tapylmady.", ""
        if not zipfile.is_zipfile(path):
            return False, "Saýlanan faýl dogry ZIP arhiw däl.", ""

        with zipfile.ZipFile(path, "r") as zf:
            names = [n.replace("\\", "/") for n in zf.namelist()]

        for name in names:
            if name.endswith("MobileStore.exe"):
                prefix = name[: -len("MobileStore.exe")]
                return True, "Windows täzeleme arhiwi tassyklandy (MobileStore.exe tapyldy).", prefix

        return False, "ZIP arhiwiň içinde MobileStore.exe tapylmady.", ""

    @staticmethod
    def prepare_and_launch_update(zip_path: Path | str) -> tuple[bool, str]:
        """Создаёт страховочный бэкап, распаковывает обновление и запускает безопасный updater.

        На Windows в собранном .exe (sys.frozen) запускает внешний .bat-скрипт, который:
        1) ждёт закрытия текущего процесса MobileStore.exe;
        2) обновляет MobileStore.exe, _internal/ и документацию, НЕ трогая data/ и backups/;
        3) запускает обновлённый MobileStore.exe.
        """
        ok, msg, prefix = UpdateService.inspect_update_zip(zip_path)
        if not ok:
            return False, msg

        backup_path = BackupService.create_backup(
            prefix="pre_update",
            apply_retention=False,
        )

        if not getattr(sys, "frozen", False) or os.name != "nt":
            return (
                False,
                (
                    f"Ätiýaçlyk nusga döredildi: {backup_path.name}\n\n"
                    "Awtomatiki täzeleme diňe Windows-da ýygnalan MobileStore.exe üçin işleýär.\n"
                    "El bilen täzelemek üçin täze ZIP-i köne papkanyň üstüne açyň, "
                    "ýöne «data» we «backups» papkalaryny pozmaň."
                ),
            )

        stage_root = Path(tempfile.mkdtemp(prefix="mobilestore_update_"))
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(stage_root)

            src_dir = (stage_root / prefix).resolve() if prefix else stage_root.resolve()
            if not (src_dir / "MobileStore.exe").exists():
                shutil.rmtree(stage_root, ignore_errors=True)
                return False, "Açylan arhiwde MobileStore.exe tapylmady."

            # Удаляем из распакованного обновления любые случайные data/ или backups/
            for protected in PROTECTED_ENTRIES:
                p_dir = src_dir / protected
                if p_dir.exists():
                    shutil.rmtree(p_dir, ignore_errors=True)

            target_dir = PROJECT_ROOT.resolve()
            pid = os.getpid()
            bat_path = stage_root / "apply_update.bat"
            bat_content = (
                "@echo off\r\n"
                "chcp 65001 >nul\r\n"
                "echo MobileStore tazelenyar, garashyn...\r\n"
                ":waitloop\r\n"
                f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul\r\n'
                "if not errorlevel 1 (\r\n"
                "    timeout /t 1 /nobreak >nul\r\n"
                "    goto waitloop\r\n"
                ")\r\n"
                "timeout /t 1 /nobreak >nul\r\n"
                f'if exist "{target_dir}\\_internal" rmdir /S /Q "{target_dir}\\_internal"\r\n'
                f'robocopy "{src_dir}" "{target_dir}" /E /XD data backups /NFL /NDL /NJH /NJS >nul\r\n'
                f'start "" "{target_dir}\\MobileStore.exe"\r\n'
                f'rmdir /S /Q "{stage_root}"\r\n'
            )
            bat_path.write_text(bat_content, encoding="utf-8")

            subprocess.Popen(
                ["cmd.exe", "/c", str(bat_path)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
            return (
                True,
                (
                    f"Ätiýaçlyk nusga döredildi ({backup_path.name}).\n"
                    "Programma häzir ýapylar, täzelener we awtomatiki gaýtadan açylar!"
                ),
            )
        except (OSError, zipfile.BadZipFile, ValueError) as err:
            shutil.rmtree(stage_root, ignore_errors=True)
            return False, f"Täzeleme taýýarlamakda ýalňyşlyk: {err}"
