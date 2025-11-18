cmake_minimum_required(VERSION 3.8)
project(robot_ros2)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(visualization_msgs REQUIRED)
find_package(cv_bridge REQUIRED)
find_package(image_transport REQUIRED)
find_package(OpenCV REQUIRED)

# Robot controller node
add_executable(robot_controller_node
  src/robot_controller_node.cpp
)

ament_target_dependencies(robot_controller_node
  rclcpp
  std_msgs
  geometry_msgs
  sensor_msgs
  tf2
  tf2_ros
  visualization_msgs
)

# Robot visualizer node (Qt-based GUI)
find_package(Qt6 COMPONENTS Core Gui Widgets QUIET)
if(Qt6_FOUND)
  add_executable(robot_visualizer_node
    src/robot_visualizer_node.cpp
  )

  ament_target_dependencies(robot_visualizer_node
    rclcpp
    std_msgs
    geometry_msgs
    sensor_msgs
    visualization_msgs
    cv_bridge
  )

  target_link_libraries(robot_visualizer_node
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    ${OpenCV_LIBS}
  )

  install(TARGETS robot_visualizer_node
    DESTINATION lib/${PROJECT_NAME}
  )
endif()

# Camera node
add_executable(camera_node
  src/camera_node.cpp
)

ament_target_dependencies(camera_node
  rclcpp
  std_msgs
  sensor_msgs
  cv_bridge
  image_transport
  OpenCV
)

target_link_libraries(camera_node
  ${OpenCV_LIBS}
)

install(TARGETS camera_node
  DESTINATION lib/${PROJECT_NAME}
)

# Install targets
install(TARGETS robot_controller_node
  DESTINATION lib/${PROJECT_NAME}
)

# Install launch files
install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

# Install Python scripts
install(PROGRAMS
  src/hand_gesture_controller.py
  DESTINATION lib/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
