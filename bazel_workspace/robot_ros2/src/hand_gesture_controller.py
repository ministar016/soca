#!/usr/bin/env python3

import cv2
import mediapipe as mp
import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String


class HandGestureController(Node):
    def __init__(self):
        super().__init__("hand_gesture_controller")

        # Publishers
        self.cmd_vel_pub = self.create_publisher(Twist, "cmd_vel", 10)
        self.status_pub = self.create_publisher(String, "hand_gesture_status", 10)
        self.debug_image_pub = self.create_publisher(Image, "hand_tracking_debug", 10)

        # Subscriber
        self.image_sub = self.create_subscription(
            Image, "camera/image_raw", self.image_callback, 10
        )

        # CV Bridge
        self.bridge = CvBridge()

        # MediaPipe Hands
        self.mp_hands = mp.solutions.hands
        self.mp_drawing = mp.solutions.drawing_utils
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,  # Detect both hands
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5,
        )

        # Control parameters
        self.declare_parameter("velocity_scale", 2.0)
        self.declare_parameter("dead_zone", 0.1)

        self.velocity_scale = self.get_parameter("velocity_scale").value
        self.dead_zone = self.get_parameter("dead_zone").value

        # Reference center position
        self.center_x = 0.5
        self.center_y = 0.5

        # Separate reference for each hand
        self.left_hand_reference_z = None
        self.right_hand_reference_z = None

        self.get_logger().info("Hand Gesture Controller started!")
        self.get_logger().info("Kontrola sa DVE RUKE:")
        self.get_logger().info("  LEVA RUKA:")
        self.get_logger().info("    - Pomeri BLIZE/DALJE -> Robot Y osa (GORE/DOLE)")
        self.get_logger().info("  DESNA RUKA:")
        self.get_logger().info("    - Pomeri LEVO/DESNO -> Robot X osa")
        self.get_logger().info("    - Pomeri GORE/DOLE -> Robot Z osa (NAPRED/NAZAD)")
        self.get_logger().info("  Referentne tacke se kalibrisu automatski")

    def calculate_hand_openness(self, hand_landmarks):
        """Izračunava koliko je šaka otvorena (0=zatvorena, 1=otvorena)"""
        # Uzmi distance between fingertips and palm
        palm = hand_landmarks.landmark[0]  # Wrist

        # Check all fingertips
        fingertips = [4, 8, 12, 16, 20]  # Thumb, Index, Middle, Ring, Pinky

        distances = []
        for tip_id in fingertips:
            tip = hand_landmarks.landmark[tip_id]
            dist = np.sqrt(
                (tip.x - palm.x) ** 2 + (tip.y - palm.y) ** 2 + (tip.z - palm.z) ** 2
            )
            distances.append(dist)

        avg_distance = np.mean(distances)
        # Normalize (typical range 0.3-0.7)
        openness = np.clip((avg_distance - 0.3) / 0.4, 0.0, 1.0)
        return openness

    def image_callback(self, msg):
        try:
            # Convert ROS image to OpenCV
            cv_image = self.bridge.imgmsg_to_cv2(msg, "rgb8")

            # Process with MediaPipe
            results = self.hands.process(cv_image)

            # Create debug image
            debug_image = cv_image.copy()

            # Initialize velocities - IMPORTANT: Keep separate for each hand
            left_vel_y = 0.0
            right_vel_x = 0.0
            right_vel_z = 0.0

            left_hand_detected = False
            right_hand_detected = False

            if results.multi_hand_landmarks and results.multi_handedness:
                for hand_landmarks, handedness in zip(
                    results.multi_hand_landmarks, results.multi_handedness
                ):
                    # Determine which hand (Left or Right from camera perspective)
                    # NOTE: MediaPipe gives mirrored labels, so we invert them
                    # If camera sees "Right", it's actually your LEFT hand
                    hand_label = handedness.classification[0].label  # "Left" or "Right"

                    # Invert the label for mirror mode
                    actual_hand = "Left" if hand_label == "Right" else "Right"

                    # Draw hand landmarks with different colors based on ACTUAL hand
                    if actual_hand == "Left":
                        # Left hand - GREEN (controls Y axis - up/down)
                        self.mp_drawing.draw_landmarks(
                            debug_image,
                            hand_landmarks,
                            self.mp_hands.HAND_CONNECTIONS,
                            self.mp_drawing.DrawingSpec(
                                color=(0, 255, 0), thickness=2, circle_radius=2
                            ),
                            self.mp_drawing.DrawingSpec(color=(0, 200, 0), thickness=2),
                        )
                        left_hand_detected = True
                    else:
                        # Right hand - BLUE (controls X and Z axes)
                        self.mp_drawing.draw_landmarks(
                            debug_image,
                            hand_landmarks,
                            self.mp_hands.HAND_CONNECTIONS,
                            self.mp_drawing.DrawingSpec(
                                color=(255, 0, 0), thickness=2, circle_radius=2
                            ),
                            self.mp_drawing.DrawingSpec(color=(200, 0, 0), thickness=2),
                        )
                        right_hand_detected = True

                    # Get hand position (using wrist as reference)
                    wrist = hand_landmarks.landmark[0]
                    middle_tip = hand_landmarks.landmark[12]  # MIDDLE_FINGER_TIP

                    hand_x = wrist.x
                    hand_y = wrist.y

                    # Depth from hand size (larger=closer, smaller=farther)
                    import math

                    hand_size = math.sqrt(
                        (middle_tip.x - wrist.x) ** 2 + (middle_tip.y - wrist.y) ** 2
                    )
                    # Scale up for better sensitivity
                    hand_depth = hand_size * 10.0

                    if actual_hand == "Left":
                        # LEFT HAND controls Y axis (up/down) via depth
                        # Calibrate reference on first detection
                        if self.left_hand_reference_z is None:
                            self.left_hand_reference_z = hand_depth
                            ref = self.left_hand_reference_z
                            self.get_logger().info(f"LEVA ruka kalibrisana: {ref:.3f}")

                        # Calculate Y velocity based on depth difference
                        z_diff = hand_depth - self.left_hand_reference_z
                        left_vel_y = -z_diff * self.velocity_scale * 5.0

                        # DEBUG: log actual depth values
                        if abs(z_diff) > 0.005:
                            self.get_logger().info(
                                f"LEVA: depth={hand_depth:.4f}, "
                                f"ref={self.left_hand_reference_z:.4f}, "
                                f"diff={z_diff:.4f}, vel_y={left_vel_y:.4f}"
                            )

                        # Draw info
                        cv2.putText(
                            debug_image,
                            f"LEFT(Y): D={hand_depth:.3f} "
                            f"R={self.left_hand_reference_z:.3f}",
                            (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (0, 255, 0),
                            2,
                        )
                        cv2.putText(
                            debug_image,
                            f"Y vel: {left_vel_y:.2f}",
                            (10, 55),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (0, 255, 0),
                            2,
                        )

                    else:  # Right hand
                        # RIGHT HAND: X and Z axes
                        # Calibrate reference on first detection
                        if self.right_hand_reference_z is None:
                            self.right_hand_reference_z = hand_depth
                            ref = self.right_hand_reference_z
                            self.get_logger().info(f"DESNA ruka kalibrisana: {ref:.3f}")

                        # X velocity: horizontal movement (inverted)
                        right_vel_x = -(hand_x - self.center_x) * self.velocity_scale

                        # Z velocity: vertical movement (inverted)
                        right_vel_z = -(hand_y - self.center_y) * self.velocity_scale

                        # Draw info
                        cv2.putText(
                            debug_image,
                            f"RIGHT(X,Z): X={hand_x:.2f}, Y={hand_y:.2f}",
                            (10, 85),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (255, 0, 0),
                            2,
                        )
                        cv2.putText(
                            debug_image,
                            f"X vel: {right_vel_x:.2f}, Z vel: {right_vel_z:.2f}",
                            (10, 110),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (255, 0, 0),
                            2,
                        )

                # Combine velocities from both hands
                vel_x = right_vel_x
                vel_y = left_vel_y
                vel_z = right_vel_z

                # Apply dead zone
                if abs(vel_x) < self.dead_zone:
                    vel_x = 0.0
                if abs(vel_y) < self.dead_zone:
                    vel_y = 0.0
                if abs(vel_z) < self.dead_zone:
                    vel_z = 0.0

                # Publish velocity command
                twist = Twist()
                twist.linear.x = vel_x
                twist.linear.y = vel_y
                twist.linear.z = vel_z
                self.cmd_vel_pub.publish(twist)

                # Publish status
                status_msg = String()
                hands_status = []
                if left_hand_detected:
                    hands_status.append(f"LEVA(Y={vel_y:.2f})")
                if right_hand_detected:
                    hands_status.append(f"DESNA(X={vel_x:.2f},Z={vel_z:.2f})")

                status_msg.data = f"Ruke: {', '.join(hands_status)}"
                self.status_pub.publish(status_msg)

                # Draw instructions
                cv2.putText(
                    debug_image,
                    "LEFT (green): CLOSER/FARTHER = UP/DOWN",
                    (10, debug_image.shape[0] - 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1,
                )
                cv2.putText(
                    debug_image,
                    "RIGHT (blue): LEFT/RIGHT, UP/DOWN = X,Z axes",
                    (10, debug_image.shape[0] - 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 0, 0),
                    1,
                )

                # Draw center crosshair
                h, w = debug_image.shape[:2]
                cx, cy = int(w * self.center_x), int(h * self.center_y)
                cv2.drawMarker(
                    debug_image, (cx, cy), (255, 255, 0), cv2.MARKER_CROSS, 30, 2
                )

            else:
                # No hands detected - stop robot and reset references
                twist = Twist()
                twist.linear.x = 0.0
                twist.linear.y = 0.0
                twist.linear.z = 0.0
                self.cmd_vel_pub.publish(twist)

                # Reset reference depths
                self.left_hand_reference_z = None
                self.right_hand_reference_z = None

                status_msg = String()
                status_msg.data = "Nema ruku - robot stopiran"
                self.status_pub.publish(status_msg)

                cv2.putText(
                    debug_image,
                    "Nema ruku - cekam detekciju...",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 255),
                    2,
                )
                cv2.putText(
                    debug_image,
                    "LEVA ruka (zelena) = GORE/DOLE",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1,
                )
                cv2.putText(
                    debug_image,
                    "DESNA ruka (plava) = LEVO/DESNO, NAPRED/NAZAD",
                    (10, 85),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 0, 0),
                    1,
                )

            # Publish debug image
            debug_msg = self.bridge.cv2_to_imgmsg(debug_image, "rgb8")
            self.debug_image_pub.publish(debug_msg)

        except Exception as e:
            self.get_logger().error(f"Error processing image: {e}")

    def destroy_node(self):
        self.hands.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = HandGestureController()

    node.get_logger().info("===========================================")
    node.get_logger().info("  👋 Hand Gesture Controller")
    node.get_logger().info("===========================================")
    node.get_logger().info("Subscribing to: /camera/image_raw")
    node.get_logger().info("Publishing to: /cmd_vel, /hand_gesture_status")
    node.get_logger().info("")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
