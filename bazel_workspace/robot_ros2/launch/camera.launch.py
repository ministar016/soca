from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
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
        ]
    )
