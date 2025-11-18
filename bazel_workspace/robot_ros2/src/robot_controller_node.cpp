#include <chrono>
#include <cmath>
#include <memory>

#include "geometry_msgs/msg/point_stamped.hpp"
#include "geometry_msgs/msg/pose_stamped.hpp"
#include "geometry_msgs/msg/transform_stamped.hpp"
#include "geometry_msgs/msg/twist.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/joint_state.hpp"
#include "std_msgs/msg/string.hpp"
#include "tf2/LinearMath/Quaternion.h"
#include "tf2_ros/transform_broadcaster.h"
#include "visualization_msgs/msg/marker.hpp"

using namespace std::chrono_literals;

class RobotController : public rclcpp::Node {
 public:
  RobotController() : Node("robot_controller") {
    // Initialize position
    x_ = 0.0;
    y_ = 0.0;
    z_ = 0.0;

    // Declare and get parameters
    this->declare_parameter("update_rate", 50.0);
    this->declare_parameter("movement_step", 0.5);

    update_rate_ = this->get_parameter("update_rate").as_double();
    movement_step_ = this->get_parameter("movement_step").as_double();

    // Publishers
    pose_pub_ = this->create_publisher<geometry_msgs::msg::PoseStamped>(
        "robot_pose", 10);
    position_pub_ = this->create_publisher<geometry_msgs::msg::PointStamped>(
        "robot_position", 10);
    status_pub_ =
        this->create_publisher<std_msgs::msg::String>("robot_status", 10);
    marker_pub_ = this->create_publisher<visualization_msgs::msg::Marker>(
        "robot_marker", 10);
    joint_state_pub_ = this->create_publisher<sensor_msgs::msg::JointState>(
        "joint_states", 10);

    // Subscribers
    cmd_vel_sub_ = this->create_subscription<geometry_msgs::msg::Twist>(
        "cmd_vel", 10,
        std::bind(&RobotController::cmdVelCallback, this,
                  std::placeholders::_1));

    // TF broadcaster
    tf_broadcaster_ = std::make_shared<tf2_ros::TransformBroadcaster>(this);

    // Timer for publishing state
    auto timer_interval = std::chrono::duration<double>(1.0 / update_rate_);
    timer_ = this->create_wall_timer(
        std::chrono::duration_cast<std::chrono::milliseconds>(timer_interval),
        std::bind(&RobotController::timerCallback, this));

    RCLCPP_INFO(this->get_logger(),
                "Robot Controller Node started with update rate: %.1f Hz",
                update_rate_);
    RCLCPP_INFO(this->get_logger(), "Listening on /cmd_vel for commands");
    RCLCPP_INFO(this->get_logger(),
                "Publishing to: /robot_pose, /robot_position, /robot_status");
  }

 private:
  void cmdVelCallback(const geometry_msgs::msg::Twist::SharedPtr msg) {
    // Update position based on velocity commands
    // linear.x -> X axis movement
    // linear.y -> Y axis movement (height)
    // linear.z -> Z axis movement

    double dt = 1.0 / update_rate_;
    x_ += msg->linear.x * dt;
    y_ += msg->linear.y * dt;
    z_ += msg->linear.z * dt;

    RCLCPP_DEBUG(this->get_logger(), "Position updated: X=%.2f, Y=%.2f, Z=%.2f",
                 x_, y_, z_);
  }

  void timerCallback() {
    auto now = this->get_clock()->now();

    // Publish pose
    publishPose(now);

    // Publish position
    publishPosition(now);

    // Publish status
    publishStatus(now);

    // Publish visualization marker
    publishMarker(now);

    // Publish joint states
    publishJointStates(now);

    // Publish TF transform
    publishTransform(now);
  }

  void publishPose(const rclcpp::Time& now) {
    auto pose_msg = geometry_msgs::msg::PoseStamped();
    pose_msg.header.stamp = now;
    pose_msg.header.frame_id = "world";

    pose_msg.pose.position.x = x_;
    pose_msg.pose.position.y = y_;
    pose_msg.pose.position.z = z_;

    pose_msg.pose.orientation.w = 1.0;
    pose_msg.pose.orientation.x = 0.0;
    pose_msg.pose.orientation.y = 0.0;
    pose_msg.pose.orientation.z = 0.0;

    pose_pub_->publish(pose_msg);
  }

  void publishPosition(const rclcpp::Time& now) {
    auto pos_msg = geometry_msgs::msg::PointStamped();
    pos_msg.header.stamp = now;
    pos_msg.header.frame_id = "world";

    pos_msg.point.x = x_;
    pos_msg.point.y = y_;
    pos_msg.point.z = z_;

    position_pub_->publish(pos_msg);
  }

  void publishStatus(const rclcpp::Time& now) {
    auto status_msg = std_msgs::msg::String();

    double distance = std::sqrt(x_ * x_ + y_ * y_ + z_ * z_);

    status_msg.data = "Status: Aktivan | Pozicija: X=" + std::to_string(x_) +
                      " Y=" + std::to_string(y_) + " Z=" + std::to_string(z_) +
                      " | Udaljenost: " + std::to_string(distance);

    status_pub_->publish(status_msg);
  }

  void publishMarker(const rclcpp::Time& now) {
    auto marker = visualization_msgs::msg::Marker();
    marker.header.frame_id = "world";
    marker.header.stamp = now;
    marker.ns = "robot";
    marker.id = 0;
    marker.type = visualization_msgs::msg::Marker::CUBE;
    marker.action = visualization_msgs::msg::Marker::ADD;

    // Position
    marker.pose.position.x = x_;
    marker.pose.position.y = y_;
    marker.pose.position.z = z_;
    marker.pose.orientation.w = 1.0;

    // Scale (body size)
    marker.scale.x = 2.0;
    marker.scale.y = 2.0;
    marker.scale.z = 2.0;

    // Color (blue)
    marker.color.r = 0.4f;
    marker.color.g = 0.6f;
    marker.color.b = 1.0f;
    marker.color.a = 0.8f;

    marker.lifetime = rclcpp::Duration::from_seconds(0);

    marker_pub_->publish(marker);

    // Head marker
    auto head_marker = visualization_msgs::msg::Marker();
    head_marker.header.frame_id = "world";
    head_marker.header.stamp = now;
    head_marker.ns = "robot";
    head_marker.id = 1;
    head_marker.type = visualization_msgs::msg::Marker::SPHERE;
    head_marker.action = visualization_msgs::msg::Marker::ADD;

    head_marker.pose.position.x = x_;
    head_marker.pose.position.y = y_ + 1.7;
    head_marker.pose.position.z = z_;
    head_marker.pose.orientation.w = 1.0;

    head_marker.scale.x = 1.0;
    head_marker.scale.y = 1.0;
    head_marker.scale.z = 1.0;

    head_marker.color.r = 1.0f;
    head_marker.color.g = 0.8f;
    head_marker.color.b = 0.4f;
    head_marker.color.a = 1.0f;

    head_marker.lifetime = rclcpp::Duration::from_seconds(0);

    marker_pub_->publish(head_marker);
  }

  void publishJointStates(const rclcpp::Time& now) {
    auto joint_state = sensor_msgs::msg::JointState();
    joint_state.header.stamp = now;

    joint_state.name = {"left_arm_joint", "right_arm_joint"};
    joint_state.position = {0.0, 0.0};
    joint_state.velocity = {0.0, 0.0};
    joint_state.effort = {0.0, 0.0};

    joint_state_pub_->publish(joint_state);
  }

  void publishTransform(const rclcpp::Time& now) {
    geometry_msgs::msg::TransformStamped transform;
    transform.header.stamp = now;
    transform.header.frame_id = "world";
    transform.child_frame_id = "robot_base_link";

    transform.transform.translation.x = x_;
    transform.transform.translation.y = y_;
    transform.transform.translation.z = z_;

    tf2::Quaternion q;
    q.setRPY(0, 0, 0);
    transform.transform.rotation.x = q.x();
    transform.transform.rotation.y = q.y();
    transform.transform.rotation.z = q.z();
    transform.transform.rotation.w = q.w();

    tf_broadcaster_->sendTransform(transform);
  }

  // Member variables
  double x_, y_, z_;
  double update_rate_;
  double movement_step_;

  rclcpp::Publisher<geometry_msgs::msg::PoseStamped>::SharedPtr pose_pub_;
  rclcpp::Publisher<geometry_msgs::msg::PointStamped>::SharedPtr position_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr status_pub_;
  rclcpp::Publisher<visualization_msgs::msg::Marker>::SharedPtr marker_pub_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr joint_state_pub_;

  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_sub_;

  std::shared_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char* argv[]) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<RobotController>();

  RCLCPP_INFO(node->get_logger(),
              "===========================================");
  RCLCPP_INFO(node->get_logger(), "  🤖 SOCA Robot Controller ROS2 Humble");
  RCLCPP_INFO(node->get_logger(),
              "===========================================");
  RCLCPP_INFO(node->get_logger(), "");
  RCLCPP_INFO(node->get_logger(), "Kontrola robota:");
  RCLCPP_INFO(node->get_logger(),
              "  rostopic pub /cmd_vel geometry_msgs/Twist ...");
  RCLCPP_INFO(node->get_logger(), "  linear.x -> X osa");
  RCLCPP_INFO(node->get_logger(), "  linear.y -> Y osa (visina)");
  RCLCPP_INFO(node->get_logger(), "  linear.z -> Z osa");
  RCLCPP_INFO(node->get_logger(), "");

  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
