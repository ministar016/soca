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
            # Camera Node
            Node(
                package="robot_ros2",
                executable="camera_node",
                name="camera",
                output="screen",
                parameters=[
                    {
                        "camera_id": 0,
                        "frame_rate": 30.0,
                        "image_width": 640,
                        "image_height": 480,
                        "camera_frame_id": "camera_link",
                    }
                ],
            ),
            # Hand Gesture Controller
            Node(
                package="robot_ros2",
                executable="hand_gesture_controller.py",
                name="hand_gesture_controller",
                output="screen",
                parameters=[
                    {
                        "velocity_scale": 2.0,
                        "dead_zone": 0.1,
                    }
                ],
            ),
        ]
    )
