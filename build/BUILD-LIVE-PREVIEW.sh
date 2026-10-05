#!/bin/sh
set -eu
# Build recipe, unexecuted in this development environment.
# Run as root on a Debian 12 build host with live-build installed and network access.
# This builds a LIVE PREVIEW, not the disk conversion/wiper installer.
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run on the dedicated Debian build host as root.' >&2
  exit 1
fi
command -v lb >/dev/null 2>&1 || { echo 'Install Debian live-build first.' >&2; exit 1; }
feather_source=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
feather_build=$(mktemp -d /tmp/feather-build.XXXXXX)
cd "$feather_build"
lb config --distribution bookworm --architectures amd64 --binary-images iso-hybrid \
  --archive-areas 'main contrib non-free non-free-firmware' --apt-recommends false \
  --debian-installer false --bootappend-live 'boot=live components username=user'
mkdir -p config/package-lists config/includes.chroot/opt/feather/agent config/includes.chroot/etc/xdg/openbox
cat > config/package-lists/feather.list.chroot <<'PACKAGES'
linux-image-amd64
live-boot
live-config
xserver-xorg
openbox
lightdm
chromium
python3
network-manager
network-manager-gnome
ca-certificates
git
remmina
remmina-plugin-rdp
espeak-ng
alsa-utils
pulseaudio
firmware-linux
firmware-iwlwifi
firmware-realtek
PACKAGES
cp "$feather_source"/agent/*.py "$feather_source"/agent/desktop.html config/includes.chroot/opt/feather/agent/
cat > config/includes.chroot/opt/feather/start-desktop.sh <<'START'
#!/bin/sh
cd /opt/feather
mkdir -p "$HOME/.local/share/feather"
python3 -m agent.server --data-dir "$HOME/.local/share/feather" >"$HOME/.local/share/feather/agent.log" 2>&1 &
feather_agent_pid=$!
trap 'kill "$feather_agent_pid" 2>/dev/null || true' EXIT
# Chromium connects after the local server has opened; the user can reload if boot is slower.
sleep 2
chromium --kiosk http://127.0.0.1:8765
START
chmod +x config/includes.chroot/opt/feather/start-desktop.sh
cat > config/includes.chroot/etc/xdg/openbox/autostart <<'AUTOSTART'
nm-applet &
/opt/feather/start-desktop.sh &
AUTOSTART
mkdir -p config/includes.chroot/etc/lightdm/lightdm.conf.d
cat > config/includes.chroot/etc/lightdm/lightdm.conf.d/50-feather.conf <<'LOGIN'
[Seat:*]
autologin-user=user
user-session=openbox
LOGIN
lb build
echo "Live preview image built under $feather_build. Its hardware/voice support still requires testing."
