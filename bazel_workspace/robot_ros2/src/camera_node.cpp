#include <chrono>
#include <memory>
#include <opencv2/opencv.hpp>

#include "cv_bridge/cv_bridge.hpp"
#include "image_transport/image_transport.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/camera_info.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "std_msgs/msg/header.hpp"

using namespace std::chrono_literals;

class CameraNode : public rclcpp::Node {
 public:
  CameraNode() : Node("camera_node") {
    // Declare parameters
    this->declare_parameter("camera_id", 0);
    this->declare_parameter("frame_rate", 30.0);
    this->declare_parameter("image_width", 640);
    this->declare_parameter("image_height", 480);
    this->declare_parameter("camera_frame_id", "camera_link");

    // Get parameters
    camera_id_ = this->get_parameter("camera_id").as_int();
    frame_rate_ = this->get_parameter("frame_rate").as_double();
    image_width_ = this->get_parameter("image_width").as_int();
    image_height_ = this->get_parameter("image_height").as_int();
    camera_frame_id_ = this->get_parameter("camera_frame_id").as_string();

    // Open camera
    cap_.open(camera_id_);
    if (!cap_.isOpened()) {
      RCLCPP_ERROR(this->get_logger(), "Ne mogu otvoriti kameru ID: %d",
                   camera_id_);
      rclcpp::shutdown();
      return;
    }

    // Set camera properties
    cap_.set(cv::CAP_PROP_FRAME_WIDTH, image_width_);
    cap_.set(cv::CAP_PROP_FRAME_HEIGHT, image_height_);
    cap_.set(cv::CAP_PROP_FPS, frame_rate_);

    // Get actual camera properties
    actual_width_ = cap_.get(cv::CAP_PROP_FRAME_WIDTH);
    actual_height_ = cap_.get(cv::CAP_PROP_FRAME_HEIGHT);
    actual_fps_ = cap_.get(cv::CAP_PROP_FPS);

    RCLCPP_INFO(this->get_logger(), "Kamera otvorena:");
    RCLCPP_INFO(this->get_logger(), "  Rezolucija: %dx%d",
                static_cast<int>(actual_width_),
                static_cast<int>(actual_height_));
    RCLCPP_INFO(this->get_logger(), "  FPS: %.1f", actual_fps_);

    // Create publishers
    image_pub_ =
        this->create_publisher<sensor_msgs::msg::Image>("camera/image_raw", 10);
    camera_info_pub_ = this->create_publisher<sensor_msgs::msg::CameraInfo>(
        "camera/camera_info", 10);

    // Create timer for capturing frames
    auto timer_interval = std::chrono::duration<double>(1.0 / frame_rate_);
    timer_ = this->create_wall_timer(
        std::chrono::duration_cast<std::chrono::milliseconds>(timer_interval),
        std::bind(&CameraNode::timerCallback, this));

    RCLCPP_INFO(this->get_logger(), "Camera node pokrenut!");
    RCLCPP_INFO(this->get_logger(), "Publishing na:");
    RCLCPP_INFO(this->get_logger(), "  /camera/image_raw");
    RCLCPP_INFO(this->get_logger(), "  /camera/camera_info");
  }

  ~CameraNode() {
    if (cap_.isOpened()) {
      cap_.release();
    }
  }

 private:
  void timerCallback() {
    cv::Mat frame;
    if (!cap_.read(frame)) {
      RCLCPP_WARN(this->get_logger(), "Ne mogu pročitati frame sa kamere");
      return;
    }

    if (frame.empty()) {
      RCLCPP_WARN(this->get_logger(), "Prazan frame");
      return;
    }

    // Convert OpenCV image to ROS message
    auto now = this->get_clock()->now();

    std_msgs::msg::Header header;
    header.stamp = now;
    header.frame_id = camera_frame_id_;

    // Convert BGR to RGB
    cv::Mat frame_rgb;
    cv::cvtColor(frame, frame_rgb, cv::COLOR_BGR2RGB);

    // Create image message
    sensor_msgs::msg::Image::SharedPtr img_msg =
        cv_bridge::CvImage(header, "rgb8", frame_rgb).toImageMsg();

    image_pub_->publish(*img_msg);

    // Publish camera info
    publishCameraInfo(now);

    frame_count_++;
    if (frame_count_ % 30 == 0) {
      RCLCPP_DEBUG(this->get_logger(), "Published %ld frames", frame_count_);
    }
  }

  void publishCameraInfo(const rclcpp::Time& now) {
    auto camera_info_msg = sensor_msgs::msg::CameraInfo();
    camera_info_msg.header.stamp = now;
    camera_info_msg.header.frame_id = camera_frame_id_;

    camera_info_msg.width = actual_width_;
    camera_info_msg.height = actual_height_;

    // Simple camera matrix (može se kalibrisati za bolju tačnost)
    camera_info_msg.k[0] = actual_width_;         // fx
    camera_info_msg.k[2] = actual_width_ / 2.0;   // cx
    camera_info_msg.k[4] = actual_width_;         // fy
    camera_info_msg.k[5] = actual_height_ / 2.0;  // cy
    camera_info_msg.k[8] = 1.0;

    camera_info_msg.distortion_model = "plumb_bob";
    camera_info_msg.d = {0.0, 0.0, 0.0, 0.0, 0.0};

    camera_info_pub_->publish(camera_info_msg);
  }

  // Member variables
  cv::VideoCapture cap_;
  int camera_id_;
  double frame_rate_;
  int image_width_;
  int image_height_;
  std::string camera_frame_id_;

  double actual_width_;
  double actual_height_;
  double actual_fps_;

  size_t frame_count_ = 0;

  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr image_pub_;
  rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr camera_info_pub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char* argv[]) {
  rclcpp::init(argc, argv);

  auto node = std::make_shared<CameraNode>();

  RCLCPP_INFO(node->get_logger(),
              "===========================================");
  RCLCPP_INFO(node->get_logger(), "  📷 SOCA Camera Node ROS2");
  RCLCPP_INFO(node->get_logger(),
              "===========================================");

  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
