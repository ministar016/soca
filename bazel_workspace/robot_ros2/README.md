# SOCA Robot ROS2 Package

ROS2 Humble package za 3D robot simulator sa Qt vizualizacijom.

## Struktura

- **robot_controller_node**: ROS2 node koji upravlja pozicijom robota
- **robot_visualizer_node**: Qt GUI za vizualizaciju i kontrolu robota
- **camera_node**: ROS2 node za stream video sa laptop kamere
- **hand_gesture_controller.py**: MediaPipe-based kontrola sa DVE RUKE za upravljanje robotom gestovima

## Instalacija

```bash
# Navigiraj u ROS2 workspace
cd ~/ros2_ws/src

# Kopiraj ili symlink ovaj paket
ln -s /home/mn/soca/bazel_workspace/robot_ros2 .

# Build paket
cd ~/ros2_ws
colcon build --packages-select robot_ros2

# Source workspace
source install/setup.bash
```

## Pokretanje

### Samo Controller Node:
```bash
ros2 run robot_ros2 robot_controller_node
```

### Samo Visualizer Node (Qt GUI):
```bash
ros2 run robot_ros2 robot_visualizer_node
```

### Kompletna simulacija (sa launch file):
```bash
ros2 launch robot_ros2 robot_full.launch.py
```

### Sa kamerom:
```bash
ros2 launch robot_ros2 robot_with_camera.launch.py
```

### Samo kamera:
```bash
ros2 launch robot_ros2 camera.launch.py
```

### Hand Gesture Control (kamera + hand tracking):
```bash
ros2 launch robot_ros2 hand_control.launch.py
```

### Kompletna kontrola rukom (sve + hand tracking):
```bash
ros2 launch robot_ros2 robot_full_hand_control.launch.py
```

## Kontrola robota

### Pomoću Hand Gesture Control - DVE RUKE (preporučeno):
**LEVA RUKA (zelena):**
- **Pomeri ruku BLIŽE/DALJE kameri**: Kontrola Y ose (visina robota)
  - Ruku bliže kameri → Robot ide GORE ⬆️
  - Ruku dalje od kamere → Robot ide DOLE ⬇️

**DESNA RUKA (plava):**
- **Pomeri ruku LEVO/DESNO**: Kontrola X ose (lateral)
- **Pomeri ruku GORE/DOLE**: Kontrola Z ose (napred/nazad)

- Drži obe ruke pred kamerom na ~30-50cm distanci
- Vizualizacija hand tracking-a sa bojama (zelena=leva, plava=desna) vidljiva u Qt GUI-u
- Referentne tačke se automatski kalibrišu za svaku ruku
- Debug vizualizacija dostupna na `/hand_tracking_debug` topic

### Pomoću Visualizer GUI:
- **WASD** ili **Arrow keys**: Kreće X/Z
- **Q/E**: Gore/Dole (Y osa)
- **R**: Reset poziciju
- **+/-**: Zoom

### Pomoću ROS2 komandi:

```bash
# Kreći robota po X osi
ros2 topic pub /cmd_vel geometry_msgs/Twist "{linear: {x: 1.0, y: 0.0, z: 0.0}}"

# Kreći robota gore (Y osa)
ros2 topic pub /cmd_vel geometry_msgs/Twist "{linear: {x: 0.0, y: 1.0, z: 0.0}}"

# Kreći robota po Z osi
ros2 topic pub /cmd_vel geometry_msgs/Twist "{linear: {x: 0.0, y: 0.0, z: 1.0}}"

# Stop robota
ros2 topic pub /cmd_vel geometry_msgs/Twist "{linear: {x: 0.0, y: 0.0, z: 0.0}}"
```

## ROS2 Topics

### Published by robot_controller_node:
- `/robot_pose` (geometry_msgs/PoseStamped): Trenutna pozicija i orijentacija
- `/robot_position` (geometry_msgs/PointStamped): Samo pozicija (X,Y,Z)
- `/robot_status` (std_msgs/String): Status robota
- `/robot_marker` (visualization_msgs/Marker): Marker za RViz
- `/joint_states` (sensor_msgs/JointState): Stanje zglobova
- `/tf` (tf2_msgs/TFMessage): Transform frames

### Subscribed by robot_controller_node:
- `/cmd_vel` (geometry_msgs/Twist): Velocity komande za kontrolu

### Published by camera_node:
- `/camera/image_raw` (sensor_msgs/Image): Raw RGB image sa kamere
- `/camera/camera_info` (sensor_msgs/CameraInfo): Informacije o kameri

### Published by hand_gesture_controller:
- `/cmd_vel` (geometry_msgs/Twist): Velocity komande bazirane na gestovima
- `/hand_gesture_status` (std_msgs/String): Status hand tracking-a
- `/hand_tracking_debug` (sensor_msgs/Image): Debug slika sa hand landmarks

## Visualizacija u RViz2

```bash
ros2 run rviz2 rviz2
```

Dodaj sledeće displays:
- **TF**: Za prikaz coordinate frames
- **Marker**: Topic `/robot_marker` za vizualizaciju robota
- Postavi **Fixed Frame** na `world`

## Parametri

- `update_rate` (default: 50.0 Hz): Učestalost ažuriranja pozicije
- `movement_step` (default: 0.5): Korak kretanja

## Zavisnosti

- ROS2 Humble/Jazzy
- rclcpp
- std_msgs
- geometry_msgs
- sensor_msgs
- tf2
- tf2_ros
- visualization_msgs
- cv_bridge
- image_transport
- OpenCV 4.x
- Qt6 (za visualizer node)
- Python 3.10+
- MediaPipe 0.10+ (za hand gesture control)
- NumPy

## Primer upotrebe

### Hand Gesture Control (najlakše):
```bash
# Pokreni sve sa hand tracking-om
ros2 launch robot_ros2 robot_full_hand_control.launch.py

# U drugom terminalu: Vidi debug vizualizaciju
ros2 run rqt_image_view rqt_image_view /hand_tracking_debug

# Proveri status hand tracking-a
ros2 topic echo /hand_gesture_status
```

### Klasična kontrola:
Terminal 1 - Pokreni controller:
```bash
ros2 run robot_ros2 robot_controller_node
```

Terminal 2 - Pokreni visualizer:
```bash
ros2 run robot_ros2 robot_visualizer_node
```

Terminal 3 - Kontroliši robota:
```bash
# Kreći napred
ros2 topic pub --once /cmd_vel geometry_msgs/Twist "{linear: {x: 1.0}}"

# Prati poziciju
ros2 topic echo /robot_position

# Proveri kameru
ros2 topic hz /camera/image_raw

# Vidi sliku u RViz2 ili:
ros2 run rqt_image_view rqt_image_view /camera/image_raw
```

## Licenca

MIT
