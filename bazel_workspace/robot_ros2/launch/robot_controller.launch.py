from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "update_rate", default_value="50.0", description="Update rate in Hz"
            ),
            DeclareLaunchArgument(
                "movement_step", default_value="0.5", description="Movement step size"
            ),
            Node(
                package="robot_ros2",
                executable="robot_controller_node",
                name="robot_controller",
                output="screen",
                parameters=[
                    {
                        "update_rate": LaunchConfiguration("update_rate"),
                        "movement_step": LaunchConfiguration("movement_step"),
                    }
                ],
                remappings=[
                    ("/cmd_vel", "/robot/cmd_vel"),
                ],
            ),
        ]
    )
