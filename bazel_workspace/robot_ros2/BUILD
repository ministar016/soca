load("@rules_cc//cc:defs.bzl", "cc_binary")
load("@rules_python//python:defs.bzl", "py_binary")

# Camera Node - captures from webcam and publishes to ROS2
cc_binary(
    name = "camera_node",
    srcs = ["src/camera_node.cpp"],
    deps = [
        "@ros2//:rclcpp",
        "@ros2//:sensor_msgs",
        "@ros2//:cv_bridge",
        "@opencv//:opencv",
    ],
    copts = ["-std=c++17"],
    linkopts = ["-pthread"],
)

# Robot Controller Node - manages robot state and velocity integration
cc_binary(
    name = "robot_controller_node",
    srcs = ["src/robot_controller_node.cpp"],
    deps = [
        "@ros2//:rclcpp",
        "@ros2//:geometry_msgs",
        "@ros2//:std_msgs",
        "@ros2//:visualization_msgs",
        "@ros2//:tf2",
        "@ros2//:tf2_ros",
    ],
    copts = ["-std=c++17"],
    linkopts = ["-pthread"],
)

# Robot Visualizer Node - Qt6 GUI showing 3D robot and camera feed
cc_binary(
    name = "robot_visualizer_node",
    srcs = ["src/robot_visualizer_node.cpp"],
    deps = [
        "@ros2//:rclcpp",
        "@ros2//:geometry_msgs",
        "@ros2//:std_msgs",
        "@ros2//:sensor_msgs",
        "@ros2//:cv_bridge",
        "@opencv//:opencv",
        "@qt6//:QtCore",
        "@qt6//:QtWidgets",
        "@qt6//:QtGui",
        "@qt6//:QtOpenGL",
        "@qt6//:QtOpenGLWidgets",
    ],
    copts = ["-std=c++17", "-fPIC"],
    linkopts = [
        "-pthread",
        "-lGL",
    ],
)

# Hand Gesture Controller - MediaPipe hand tracking for robot control
py_binary(
    name = "hand_gesture_controller",
    srcs = ["src/hand_gesture_controller.py"],
    main = "src/hand_gesture_controller.py",
    deps = [
        "@pip//opencv_python:pkg",
        "@pip//mediapipe:pkg",
        "@pip//numpy:pkg",
    ],
    python_version = "PY3",
)
