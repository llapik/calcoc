"""Bootloader repair — GRUB, Windows BCD, MBR/GPT restoration."""

import os
import subprocess
from dataclasses import dataclass

from src.core.logger import get_logger

log = get_logger("repair.bootloader")


@dataclass
class BootRepairResult:
    success: bool = False
    action: str = ""
    details: str = ""
    backup_path: str = ""


def detect_boot_type() -> str:
    """Detect whether the system uses UEFI or Legacy BIOS boot."""
    if os.path.isdir("/sys/firmware/efi"):
        return "UEFI"
    return "Legacy"


def fix_grub(root_partition: str, boot_device: str, efi: bool = False) -> BootRepairResult:
    """Reinstall GRUB on a Linux system.

    Args:
        root_partition: Root partition device (e.g. /dev/sda2).
        boot_device: Device to install GRUB to (e.g. /dev/sda).
        efi: Whether to use UEFI mode.
    """
    mount_point = "/mnt/repair_root"

    try:
        # Mount the root partition
        os.makedirs(mount_point, exist_ok=True)
        subprocess.check_call(["mount", root_partition, mount_point], timeout=30)

        # Bind mount necessary filesystems
        for fs in ["dev", "proc", "sys"]:
            target = os.path.join(mount_point, fs)
            os.makedirs(target, exist_ok=True)
            subprocess.check_call(["mount", "--bind", f"/{fs}", target], timeout=10)

        if efi:
            efi_dir = os.path.join(mount_point, "boot", "efi")
            os.makedirs(efi_dir, exist_ok=True)
            # Try to find and mount EFI partition
            subprocess.run(
                ["mount", f"{boot_device}1", efi_dir],
                timeout=10, capture_output=True,
            )

        # Reinstall GRUB
        if efi:
            cmd = [
                "chroot", mount_point,
                "grub-install", "--target=x86_64-efi", "--efi-directory=/boot/efi",
                "--bootloader-id=GRUB",
            ]
        else:
            cmd = ["chroot", mount_point, "grub-install", boot_device]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        # Update GRUB config
        subprocess.run(
            ["chroot", mount_point, "update-grub"],
            capture_output=True, text=True, timeout=120,
        )

        return BootRepairResult(
            success=proc.returncode == 0,
            action="fix_grub",
            details=proc.stdout + proc.stderr,
        )
    except Exception as exc:
        return BootRepairResult(success=False, action="fix_grub", details=str(exc))
    finally:
        # Cleanup mounts
        for fs in ["sys", "proc", "dev"]:
            subprocess.run(
                ["umount", os.path.join(mount_point, fs)],
                capture_output=True, timeout=10,
            )
        subprocess.run(["umount", mount_point], capture_output=True, timeout=10)


def fix_windows_bcd(windows_partition: str, efi_partition: str | None = None) -> BootRepairResult:
    """Attempt to repair Windows Boot Configuration Data."""
    mount_point = "/mnt/repair_win"

    try:
        os.makedirs(mount_point, exist_ok=True)
        subprocess.check_call(["mount", "-t", "ntfs-3g", windows_partition, mount_point], timeout=30)

        bcd_path = os.path.join(mount_point, "Boot", "BCD")
        if not os.path.isfile(bcd_path):
            bcd_path = os.path.join(mount_point, "EFI", "Microsoft", "Boot", "BCD")

        if os.path.isfile(bcd_path):
            return BootRepairResult(
                success=True,
                action="fix_windows_bcd",
                details=(
                    "BCD файл найден. Для полного восстановления загрузчика Windows "
                    "рекомендуется использовать среду восстановления Windows (bootrec /rebuildbcd)."
                ),
            )
        else:
            return BootRepairResult(
                success=False,
                action="fix_windows_bcd",
                details="BCD файл не найден. Возможно, требуется полная переустановка загрузчика.",
            )
    except Exception as exc:
        return BootRepairResult(success=False, action="fix_windows_bcd", details=str(exc))
    finally:
        subprocess.run(["umount", mount_point], capture_output=True, timeout=10)


def backup_mbr(device: str, backup_path: str) -> BootRepairResult:
    """Backup MBR (first 512 bytes) of a device."""
    try:
        subprocess.check_call(
            ["dd", "if=" + device, "of=" + backup_path, "bs=512", "count=1"],
            timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return BootRepairResult(
            success=True,
            action="backup_mbr",
            details=f"MBR сохранён в {backup_path}",
            backup_path=backup_path,
        )
    except Exception as exc:
        return BootRepairResult(success=False, action="backup_mbr", details=str(exc))


def restore_mbr(device: str, backup_path: str) -> BootRepairResult:
    """Restore MBR from backup."""
    if not os.path.isfile(backup_path):
        return BootRepairResult(
            success=False,
            action="restore_mbr",
            details=f"Файл резервной копии не найден: {backup_path}",
        )
    try:
        subprocess.check_call(
            ["dd", "if=" + backup_path, "of=" + device, "bs=446", "count=1"],
            timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return BootRepairResult(
            success=True,
            action="restore_mbr",
            details=f"MBR восстановлен из {backup_path}",
        )
    except Exception as exc:
        return BootRepairResult(success=False, action="restore_mbr", details=str(exc))
