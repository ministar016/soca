# SOCA Robot - Bazel Build

3D robot simulator sa hand gesture kontrolom koristeći MediaPipe.

## Struktura

- **robot_controller_node**: Node koji upravlja pozicijom robota
- **robot_visualizer_node**: Qt6 GUI za vizualizaciju i kontrolu robota
- **camera_node**: Stream video sa laptop kamere (OpenCV)
- **hand_gesture_controller**: MediaPipe-based dual-hand kontrola

## Build

```bash
cd bazel_workspace

# Build pojedinačnih node-ova
bazel build //robot_ros2:camera_node
bazel build //robot_ros2:robot_controller_node
bazel build //robot_ros2:robot_visualizer_node

# Ili build svega odjednom
bazel build //robot_ros2:all
```

## Pokretanje

**Napomena**: Za sada, dok Bazel dependencies nisu konfigurisani, koristi ROS2:

```bash
# Terminal 1: Robot controller
ros2 run robot_ros2 robot_controller_node

# Terminal 2: Camera
ros2 run robot_ros2 camera_node

# Terminal 3: Hand gesture controller
ros2 run robot_ros2 hand_gesture_controller.py

# Terminal 4: Visualizer
ros2 run robot_ros2 robot_visualizer_node
```

## Kontrola

### Dual Hand Control:
- **LEVA RUKA** (zelena):
  - Pomeri ruku **BLIŽE/DALJE** od kamere → Robot **GORE/DOLE** (Y osa)
  - Automatska kalibracija depth reference-a pri prvoj detekciji

- **DESNA RUKA** (plava):
  - Pomeri ruku **LEVO/DESNO** → Robot **LEVO/DESNO** (X osa)
  - Pomeri ruku **GORE/DOLE** → Robot **NAPRED/NAZAD** (Z osa)

### Keyboard (u visualizer prozoru):
- **W/↑**: Napred (Z+)
- **S/↓**: Nazad (Z-)
- **A/←**: Levo (X-)
- **D/→**: Desno (X+)
- **Q**: Gore (Y+)
- **E**: Dole (Y-)
- **R**: Reset na (0,0,0)
- **ESC**: Izlaz

## Dependencies

Za build:
- Bazel 7.x
- C++17 compiler
- Qt6
- OpenCV
- ROS2 (za sada - dok Bazel dependencies nisu konfigurisani)
- MediaPipe
- Python 3.12+

## TODO

- [ ] Konfigurisati Bazel external dependencies za ROS2
- [ ] Dodati Bazel rules za Qt6 MOC/UIC
- [ ] Migirati Python dependencies u Bazel
