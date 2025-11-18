load("@rules_cc//cc:defs.bzl", "cc_binary", "cc_library")
load("@rules_python//python:defs.bzl", "py_binary")

# Camera Node
cc_binary(
    name = "camera_node",
    srcs = ["src/camera_node.cpp"],
    deps = [
        "@rclcpp",
        "@std_msgs",
        "@sensor_msgs",
        "@opencv",
    ],
    copts = ["-std=c++17"],
)

# Robot Controller Node
cc_binary(
    name = "robot_controller_node",
    srcs = ["src/robot_controller_node.cpp"],
    deps = [
        "@rclcpp",
        "@std_msgs",
        "@geometry_msgs",
        "@sensor_msgs",
        "@tf2",
        "@tf2_ros",
        "@visualization_msgs",
    ],
    copts = ["-std=c++17"],
)

# Robot Visualizer Node (Qt6)
cc_binary(
    name = "robot_visualizer_node",
    srcs = ["src/robot_visualizer_node.cpp"],
    deps = [
        "@rclcpp",
        "@std_msgs",
        "@geometry_msgs",
        "@sensor_msgs",
        "@visualization_msgs",
        "@opencv",
        "@qt6//:QtCore",
        "@qt6//:QtGui",
        "@qt6//:QtWidgets",
    ],
    copts = ["-std=c++17", "-fPIC"],
)

# Hand Gesture Controller (Python)
py_binary(
    name = "hand_gesture_controller",
    srcs = ["src/hand_gesture_controller.py"],
    main = "src/hand_gesture_controller.py",
    deps = [
        # ROS2 Python dependencies would go here
        # MediaPipe, OpenCV dependencies
    ],
    python_version = "PY3",
)
