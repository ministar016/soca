#!/bin/bash
set -e

echo "===================================
  📦 Building SOCA Robot AppImage
===================================
"

APP_NAME="SOCA_Robot"
APPDIR="${APP_NAME}.AppDir"
APPIMAGE="${APP_NAME}-x86_64.AppImage"

# Clean
rm -rf "$APPDIR" "$APPIMAGE" 2>/dev/null || true

# Create structure
mkdir -p "$APPDIR"/{usr/{bin,lib,share/{applications,icons/hicolor/256x256/apps}},ros2}

echo "[1/5] Copying binaries from colcon build..."
INSTALL_DIR="../install/robot_ros2"
if [ ! -d "$INSTALL_DIR" ]; then
    echo "ERROR: No install directory found. Run: colcon build"
    exit 1
fi

cp "$INSTALL_DIR/lib/robot_ros2/camera_node" "$APPDIR/usr/bin/"
cp "$INSTALL_DIR/lib/robot_ros2/robot_controller_node" "$APPDIR/usr/bin/"
cp "$INSTALL_DIR/lib/robot_ros2/robot_visualizer_node" "$APPDIR/usr/bin/"
cp "$INSTALL_DIR/lib/robot_ros2/hand_gesture_controller" "$APPDIR/usr/bin/"
chmod +x "$APPDIR/usr/bin"/*

echo "[2/5] Copying ROS2 libraries..."
# Copy essential ROS2 shared libraries
for lib in librclcpp.so librcl.so librcutils.so librmw.so librosidl_runtime_c.so \
           librosidl_typesupport_cpp.so libtf2.so libtf2_ros.so libcv_bridge.so; do
    find /opt/ros/jazzy/lib -name "$lib*" -exec cp -P {} "$APPDIR/usr/lib/" \; 2>/dev/null || true
done

echo "[3/5] Creating launcher..."
cat > "$APPDIR/usr/bin/launch_robot" << 'LAUNCHER'
#!/bin/bash
APPDIR="$(dirname "$(dirname "$(readlink -f "$0")")")"
export LD_LIBRARY_PATH="$APPDIR/usr/lib:/opt/ros/jazzy/lib:$LD_LIBRARY_PATH"
export PATH="$APPDIR/usr/bin:$PATH"

# Source ROS2
if [ -f "/opt/ros/jazzy/setup.bash" ]; then
    source /opt/ros/jazzy/setup.bash
fi

echo "=================================="
echo "  🤖 SOCA Robot System"
echo "=================================="
echo ""

# Launch nodes
"$APPDIR/usr/bin/camera_node" &
sleep 0.5
"$APPDIR/usr/bin/robot_controller_node" &
sleep 0.5
"$APPDIR/usr/bin/robot_visualizer_node" &
sleep 1

echo "✅ Nodes started! Control with hands:"
echo "  LEFT:  Depth → Y"
echo "  RIGHT: X/Y → Robot X/Z"
echo ""

"$APPDIR/usr/bin/hand_gesture_controller"

# Cleanup
pkill -P $$
LAUNCHER
chmod +x "$APPDIR/usr/bin/launch_robot"

echo "[4/5] Creating desktop files..."
cat > "$APPDIR/soca_robot.desktop" << 'DESKTOP'
[Desktop Entry]
Name=SOCA Robot
Exec=launch_robot
Icon=robot
Type=Application
Categories=Science;Education;
Terminal=true
DESKTOP
cp "$APPDIR/soca_robot.desktop" "$APPDIR/usr/share/applications/"

echo "🤖" > "$APPDIR/robot.png"
cp "$APPDIR/robot.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/"

cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
APPDIR="$(dirname "$(readlink -f "$0")")"
export PATH="$APPDIR/usr/bin:$PATH"
export LD_LIBRARY_PATH="$APPDIR/usr/lib:$LD_LIBRARY_PATH"
exec "$APPDIR/usr/bin/launch_robot" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

echo "[5/5] Building AppImage..."
if [ ! -f "appimagetool-x86_64.AppImage" ]; then
    wget -q --show-progress https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x appimagetool-x86_64.AppImage
fi

ARCH=x86_64 ./appimagetool-x86_64.AppImage --appimage-extract-and-run "$APPDIR" "$APPIMAGE" 2>&1 | grep -v "WARNING"

if [ -f "$APPIMAGE" ]; then
    chmod +x "$APPIMAGE"
    echo ""
    echo "==================================="
    echo "  ✅ AppImage created!"
    echo "==================================="
    echo ""
    echo "File: $APPIMAGE"
    echo "Size: $(du -h "$APPIMAGE" | cut -f1)"
    echo ""
    echo "Run: ./$APPIMAGE --appimage-extract-and-run"
    echo "(FUSE not available, use --appimage-extract-and-run)"
else
    echo "ERROR: Build failed"
    exit 1
fi
