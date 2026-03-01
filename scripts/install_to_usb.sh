#!/usr/bin/env bash
# Install AI PC Repair & Optimizer to a USB drive.
#
# Creates 3 partitions:
#   1. EFI System Partition (512 MB, FAT32)
#   2. System (squashfs + boot, ext4)
#   3. Data (remaining space, ext4 — models, backups, telemetry)
#
# Usage: sudo bash scripts/install_to_usb.sh /dev/sdX
#
# WARNING: This will ERASE ALL DATA on the target device!

set -euo pipefail

USB_DEV="${1:-}"

if [ -z "$USB_DEV" ]; then
    echo "Usage: sudo $0 /dev/sdX"
    echo ""
    echo "Available USB devices:"
    lsblk -dpo NAME,SIZE,MODEL,TRAN | grep usb || echo "  (none found)"
    exit 1
fi

# Safety checks
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root."
    exit 1
fi

if [ ! -b "$USB_DEV" ]; then
    echo "ERROR: $USB_DEV is not a block device."
    exit 1
fi

# Check it's actually a removable device
REMOVABLE=$(cat "/sys/block/$(basename "$USB_DEV")/removable" 2>/dev/null || echo "0")
if [ "$REMOVABLE" != "1" ]; then
    echo "WARNING: $USB_DEV does not appear to be a removable device!"
    echo "If you are sure, set FORCE=1 environment variable."
    if [ "${FORCE:-0}" != "1" ]; then
        exit 1
    fi
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== AI PC Repair & Optimizer — USB Installer ==="
echo "Target device: $USB_DEV"
echo ""
echo "WARNING: ALL DATA ON $USB_DEV WILL BE ERASED!"
read -p "Type 'YES' to continue: " CONFIRM
if [ "$CONFIRM" != "YES" ]; then
    echo "Aborted."
    exit 1
fi

# ---------------------------------------------------------------
# Step 1: Partition the USB drive
# ---------------------------------------------------------------
echo "[1/5] Partitioning ${USB_DEV}..."

# Unmount any existing partitions
umount "${USB_DEV}"* 2>/dev/null || true

# Create GPT partition table
parted -s "$USB_DEV" mklabel gpt

# Partition 1: EFI (512 MB)
parted -s "$USB_DEV" mkpart primary fat32 1MiB 513MiB
parted -s "$USB_DEV" set 1 esp on

# Partition 2: System (8 GB)
parted -s "$USB_DEV" mkpart primary ext4 513MiB 8705MiB

# Partition 3: Data (remaining)
parted -s "$USB_DEV" mkpart primary ext4 8705MiB 100%

# Wait for kernel to recognize partitions
partprobe "$USB_DEV"
sleep 2

# Detect partition naming (sdX1 vs sdXp1)
if [ -b "${USB_DEV}1" ]; then
    P1="${USB_DEV}1"
    P2="${USB_DEV}2"
    P3="${USB_DEV}3"
elif [ -b "${USB_DEV}p1" ]; then
    P1="${USB_DEV}p1"
    P2="${USB_DEV}p2"
    P3="${USB_DEV}p3"
else
    echo "ERROR: Cannot detect partitions on ${USB_DEV}"
    exit 1
fi

# ---------------------------------------------------------------
# Step 2: Format partitions
# ---------------------------------------------------------------
echo "[2/5] Formatting partitions..."

mkfs.vfat -F 32 -n "EFI" "$P1"
mkfs.ext4 -L "AIREPAIR" "$P2"
mkfs.ext4 -L "AIREPAIR_DATA" "$P3"

# ---------------------------------------------------------------
# Step 3: Install system
# ---------------------------------------------------------------
echo "[3/5] Installing system..."

MNT_SYS="/mnt/calcoc_sys"
MNT_EFI="/mnt/calcoc_efi"
MNT_DATA="/mnt/calcoc_data"

mkdir -p "$MNT_SYS" "$MNT_EFI" "$MNT_DATA"
mount "$P2" "$MNT_SYS"
mount "$P1" "$MNT_EFI"
mount "$P3" "$MNT_DATA"

# Check if ISO was built
ISO="${PROJECT_DIR}/calcoc.iso"
if [ -f "$ISO" ]; then
    # Extract ISO contents
    mkdir -p /tmp/calcoc_iso
    mount -o loop "$ISO" /tmp/calcoc_iso
    cp -r /tmp/calcoc_iso/* "$MNT_SYS/"
    umount /tmp/calcoc_iso
else
    # Direct copy from project
    echo "No ISO found, copying directly from project..."
    mkdir -p "$MNT_SYS"/{boot/grub,opt/calcoc}
    cp -r "${PROJECT_DIR}/src" "$MNT_SYS/opt/calcoc/src"
    cp -r "${PROJECT_DIR}/config" "$MNT_SYS/opt/calcoc/config"
    cp -r "${PROJECT_DIR}/data" "$MNT_SYS/opt/calcoc/data"
    cp "${PROJECT_DIR}/requirements.txt" "$MNT_SYS/opt/calcoc/"
    cp "${PROJECT_DIR}/config/grub/grub.cfg" "$MNT_SYS/boot/grub/"
fi

# ---------------------------------------------------------------
# Step 4: Set up data partition
# ---------------------------------------------------------------
echo "[4/5] Setting up data partition..."

mkdir -p "$MNT_DATA"/{models,backups,knowledge,clamav,logs}

# Copy knowledge base
if [ -d "${PROJECT_DIR}/data/knowledge" ]; then
    cp -r "${PROJECT_DIR}/data/knowledge/"* "$MNT_DATA/knowledge/" 2>/dev/null || true
fi

echo "Place GGUF model files in ${MNT_DATA}/models/"

# ---------------------------------------------------------------
# Step 5: Install GRUB
# ---------------------------------------------------------------
echo "[5/5] Installing bootloader..."

# UEFI boot
mkdir -p "$MNT_EFI/EFI/BOOT"
if command -v grub-install &>/dev/null; then
    grub-install --target=x86_64-efi --efi-directory="$MNT_EFI" \
        --boot-directory="$MNT_SYS/boot" --removable --no-nvram 2>/dev/null || true

    # Legacy BIOS boot
    grub-install --target=i386-pc --boot-directory="$MNT_SYS/boot" \
        "$USB_DEV" 2>/dev/null || true
fi

# ---------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------
sync
umount "$MNT_DATA"
umount "$MNT_EFI"
umount "$MNT_SYS"

echo ""
echo "=== Installation complete! ==="
echo "USB device: $USB_DEV"
echo ""
echo "Next steps:"
echo "  1. Copy GGUF model files to the 'models' directory on the DATA partition"
echo "  2. (Optional) Run 'freshclam' on the USB to update antivirus databases"
echo "  3. Boot any PC from this USB drive"
