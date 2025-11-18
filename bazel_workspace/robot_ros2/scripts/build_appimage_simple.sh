#!/bin/bash
# Simplified AppImage - bundles source and builds on first run

set -e

echo "==================================="
echo "  📦 Building SOCA Robot AppImage"
echo "==================================="

APP_NAME="SOCA_Robot"
APPDIR="${APP_NAME}.AppDir"
APPIMAGE="${APP_NAME}-x86_64.AppImage"

rm -rf "$APPDIR" "$APPIMAGE" 2>/dev/null || true

mkdir -p "$APPDIR"/{usr/{bin,share/{applications,icons/hicolor/256x256/apps}},ros2_ws}

echo "[1/4] Copying robot package..."
cp -r ../src "$APPDIR/ros2_ws/"
cp ../CMakeLists.txt ../package.xml "$APPDIR/ros2_ws/" 2>/dev/null || true

echo "[2/4] Creating launcher..."
cat > "$APPDIR/usr/bin/soca_robot" << 'LAUNCHER'
#!/bin/bash
APPDIR="$(dirname "$(dirname "$(readlink -f "$0")")")"

source /opt/ros/jazzy/setup.bash 2>/dev/null || {
    echo "ERROR: ROS2 Jazzy required"
    exit 1
}

WS="$HOME/.soca_robot_ws"
if [ ! -d "$WS/install" ]; then
    echo "First run - building..."
    mkdir -p "$WS/src/robot_ros2"
    cp -r "$APPDIR/ros2_ws"/* "$WS/src/robot_ros2/"
    cd "$WS"
    colcon build --packages-select robot_ros2
fi

source "$WS/install/setup.bash"
cd "$WS"

ros2 run robot_ros2 camera_node &
sleep 0.5
ros2 run robot_ros2 robot_controller_node &
sleep 0.5
ros2 run robot_ros2 robot_visualizer_node &
sleep 0.5

echo "✅ Ready! Control with hands"
ros2 run robot_ros2 hand_gesture_controller
pkill -P $$
LAUNCHER
chmod +x "$APPDIR/usr/bin/soca_robot"

echo "[3/4] Desktop files..."
cat > "$APPDIR/soca_robot.desktop" << 'DESKTOP'
[Desktop Entry]
Name=SOCA Robot
Exec=soca_robot
Icon=robot
Type=Application
Categories=Robotics;
Terminal=true
DESKTOP
cp "$APPDIR/soca_robot.desktop" "$APPDIR/usr/share/applications/"

echo "🤖" > "$APPDIR/.DirIcon"

cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
APPDIR="$(dirname "$(readlink -f "$0")")"
export PATH="$APPDIR/usr/bin:$PATH"
exec "$APPDIR/usr/bin/soca_robot" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

echo "[4/4] Building AppImage..."
[ ! -f "appimagetool-x86_64.AppImage" ] && {
    wget -q https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x appimagetool-x86_64.AppImage
}

ARCH=x86_64 ./appimagetool-x86_64.AppImage "$APPDIR" "$APPIMAGE" >/dev/null 2>&1

echo ""
echo "✅ Done: $APPIMAGE ($(du -h "$APPIMAGE" | cut -f1))"
echo "Run: ./$APPIMAGE"
