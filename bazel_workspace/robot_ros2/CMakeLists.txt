cmake_minimum_required(VERSION 3.8)
project(robot_ros2)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(visualization_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(cv_bridge REQUIRED)
find_package(image_transport REQUIRED)
find_package(OpenCV REQUIRED)
find_package(Qt6 REQUIRED COMPONENTS Core Widgets Gui OpenGL OpenGLWidgets)

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

# Camera Node
add_executable(camera_node src/camera_node.cpp)
ament_target_dependencies(camera_node rclcpp sensor_msgs cv_bridge image_transport)
target_link_libraries(camera_node ${OpenCV_LIBS})

# Robot Controller Node
add_executable(robot_controller_node src/robot_controller_node.cpp)
ament_target_dependencies(robot_controller_node rclcpp geometry_msgs std_msgs visualization_msgs tf2 tf2_ros)

# Robot Visualizer Node
add_executable(robot_visualizer_node src/robot_visualizer_node.cpp)
ament_target_dependencies(robot_visualizer_node rclcpp geometry_msgs std_msgs sensor_msgs cv_bridge)
target_link_libraries(robot_visualizer_node
  Qt6::Core
  Qt6::Widgets
  Qt6::Gui
  Qt6::OpenGL
  Qt6::OpenGLWidgets
  ${OpenCV_LIBS}
)

# Install C++ executables
install(TARGETS
  camera_node
  robot_controller_node
  robot_visualizer_node
  DESTINATION lib/${PROJECT_NAME}
)

# Install Python scripts
install(PROGRAMS
  src/hand_gesture_controller.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME hand_gesture_controller
)

ament_package()
