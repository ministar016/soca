#!/bin/bash
# Launch all ROS2 robot nodes

set -e

# Source ROS2 environment
source /opt/ros/jazzy/setup.bash 2>/dev/null || true

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$(dirname "$SCRIPT_DIR")"

echo "==================================="
echo "  🤖 SOCA Robot System Launcher"
echo "==================================="
echo ""
echo "Starting all nodes..."
echo ""

# Start camera node in background
echo "[1/4] Starting camera_node..."
"${BIN_DIR}/camera_node" &
CAMERA_PID=$!
sleep 1

# Start robot controller node in background
echo "[2/4] Starting robot_controller_node..."
"${BIN_DIR}/robot_controller_node" &
CONTROLLER_PID=$!
sleep 1

# Start visualizer node in background
echo "[3/4] Starting robot_visualizer_node..."
"${BIN_DIR}/robot_visualizer_node" &
VISUALIZER_PID=$!
sleep 1

# Start hand gesture controller in foreground
echo "[4/4] Starting hand_gesture_controller..."
echo ""
echo "==================================="
echo "  ✅ All nodes started!"
echo "==================================="
echo ""
echo "Control the robot with your hands:"
echo "  LEFT HAND:  Move closer/farther → Y axis (up/down)"
echo "  RIGHT HAND: Move left/right → X axis"
echo "              Move up/down → Z axis (forward/back)"
echo ""
echo "Press Ctrl+C to stop all nodes"
echo ""

"${BIN_DIR}/hand_gesture_controller"

# Cleanup on exit
cleanup() {
    echo ""
    echo "Stopping all nodes..."
    kill $CAMERA_PID $CONTROLLER_PID $VISUALIZER_PID 2>/dev/null || true
    wait
    echo "✅ All nodes stopped"
}

trap cleanup EXIT INT TERM
