from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            # Robot Controller
            Node(
                package="robot_ros2",
                executable="robot_controller_node",
                name="robot_controller",
                output="screen",
                parameters=[
                    {
                        "update_rate": 50.0,
                        "movement_step": 0.5,
                    }
                ],
            ),
            # Robot Visualizer (Qt GUI)
            Node(
                package="robot_ros2",
                executable="robot_visualizer_node",
                name="robot_visualizer",
                output="screen",
            ),
        ]
    )
