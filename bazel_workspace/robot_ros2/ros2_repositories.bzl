"""ROS2 Jazzy system dependencies"""

def _ros2_repository_impl(repository_ctx):
    """Implementation for ROS2 system repository"""
    ros2_prefix = repository_ctx.os.environ.get("AMENT_PREFIX_PATH", "/opt/ros/jazzy")

    # Create BUILD file for ROS2 libraries
    repository_ctx.file("BUILD.bazel", """
package(default_visibility = ["//visibility:public"])

cc_library(
    name = "rclcpp",
    hdrs = glob(["include/rclcpp/**/*.hpp", "include/rclcpp/**/*.h"]),
    includes = ["include"],
    linkopts = ["-lrclcpp"],
)

cc_library(
    name = "rclpy",
    hdrs = glob(["include/rclpy/**/*.hpp", "include/rclpy/**/*.h"]),
    includes = ["include"],
)

cc_library(
    name = "std_msgs",
    hdrs = glob(["include/std_msgs/**/*.hpp", "include/std_msgs/**/*.h"]),
    includes = ["include"],
    deps = [":rclcpp"],
)

cc_library(
    name = "sensor_msgs",
    hdrs = glob(["include/sensor_msgs/**/*.hpp", "include/sensor_msgs/**/*.h"]),
    includes = ["include"],
    deps = [":rclcpp", ":std_msgs"],
)

cc_library(
    name = "geometry_msgs",
    hdrs = glob(["include/geometry_msgs/**/*.hpp", "include/geometry_msgs/**/*.h"]),
    includes = ["include"],
    deps = [":rclcpp", ":std_msgs"],
)

cc_library(
    name = "visualization_msgs",
    hdrs = glob(["include/visualization_msgs/**/*.hpp"]),
    includes = ["include"],
    deps = [":rclcpp", ":std_msgs", ":geometry_msgs"],
)

cc_library(
    name = "tf2",
    hdrs = glob(["include/tf2/**/*.hpp", "include/tf2/**/*.h"]),
    includes = ["include"],
    linkopts = ["-ltf2"],
)

cc_library(
    name = "tf2_ros",
    hdrs = glob(["include/tf2_ros/**/*.hpp", "include/tf2_ros/**/*.h"]),
    includes = ["include"],
    linkopts = ["-ltf2_ros"],
    deps = [":tf2", ":rclcpp"],
)

cc_library(
    name = "cv_bridge",
    hdrs = glob(["include/cv_bridge/**/*.hpp", "include/cv_bridge/**/*.h"]),
    includes = ["include"],
    linkopts = ["-lcv_bridge"],
    deps = [":sensor_msgs"],
)
""")

    # Symlink ROS2 include directory
    repository_ctx.symlink(ros2_prefix + "/include", "include")

ros2_repository = repository_rule(
    implementation = _ros2_repository_impl,
    local = True,
    environ = ["AMENT_PREFIX_PATH"],
)
