#include <QApplication>
#include <QHBoxLayout>
#include <QImage>
#include <QKeyEvent>
#include <QLabel>
#include <QMainWindow>
#include <QPainter>
#include <QPixmap>
#include <QPushButton>
#include <QTimer>
#include <QVBoxLayout>
#include <QWidget>
#include <cmath>
#include <memory>
#include <opencv2/opencv.hpp>

#include "cv_bridge/cv_bridge.hpp"
#include "geometry_msgs/msg/point_stamped.hpp"
#include "geometry_msgs/msg/twist.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "std_msgs/msg/string.hpp"

class Robot3DWidget : public QWidget {
 private:
  float x, y, z;
  float scale;
  float rotationX, rotationY;
  QTimer* timer;
  QLabel* xLabel;
  QLabel* yLabel;
  QLabel* zLabel;
  QLabel* statusLabel;

  // ROS2 publisher and subscriber
  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_pub_;
  rclcpp::Subscription<geometry_msgs::msg::PointStamped>::SharedPtr
      position_sub_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr hand_image_sub_;
  std::shared_ptr<rclcpp::Node> ros_node_;
  QLabel* hand_image_label_;
  QPixmap current_hand_image_;

 public:
  Robot3DWidget(QLabel* xLbl, QLabel* yLbl, QLabel* zLbl, QLabel* statusLbl,
                QLabel* handImageLbl, std::shared_ptr<rclcpp::Node> node,
                QWidget* parent = nullptr)
      : QWidget(parent),
        xLabel(xLbl),
        yLabel(yLbl),
        zLabel(zLbl),
        statusLabel(statusLbl),
        hand_image_label_(handImageLbl),
        ros_node_(node) {
    x = 0.0f;
    y = 0.0f;
    z = 0.0f;
    scale = 50.0f;
    rotationX = 30.0f;
    rotationY = 45.0f;

    setMinimumSize(600, 600);
    setFocusPolicy(Qt::StrongFocus);

    timer = new QTimer(this);
    connect(timer, &QTimer::timeout, this, QOverload<>::of(&QWidget::update));
    timer->start(16);  // ~60 FPS

    // Create ROS2 publisher
    cmd_vel_pub_ =
        ros_node_->create_publisher<geometry_msgs::msg::Twist>("cmd_vel", 10);

    // Create ROS2 subscriber for robot position
    position_sub_ =
        ros_node_->create_subscription<geometry_msgs::msg::PointStamped>(
            "robot_position", 10,
            [this](const geometry_msgs::msg::PointStamped::SharedPtr msg) {
              this->updatePosition(msg->point.x, msg->point.y, msg->point.z);
            });

    // Create ROS2 subscriber for hand tracking debug image
    hand_image_sub_ = ros_node_->create_subscription<sensor_msgs::msg::Image>(
        "hand_tracking_debug", 10,
        [this](const sensor_msgs::msg::Image::SharedPtr msg) {
          try {
            // Convert ROS image to OpenCV
            cv_bridge::CvImagePtr cv_ptr = cv_bridge::toCvCopy(msg, "bgr8");

            // Convert to QImage
            QImage qimg(cv_ptr->image.data, cv_ptr->image.cols,
                        cv_ptr->image.rows, cv_ptr->image.step,
                        QImage::Format_RGB888);
            qimg = qimg.rgbSwapped();  // BGR to RGB

            // Update the label with scaled image
            if (hand_image_label_) {
              current_hand_image_ = QPixmap::fromImage(qimg).scaled(
                  320, 240, Qt::KeepAspectRatio, Qt::SmoothTransformation);
              hand_image_label_->setPixmap(current_hand_image_);
            }
          } catch (const cv_bridge::Exception& e) {
            RCLCPP_ERROR(ros_node_->get_logger(), "cv_bridge exception: %s",
                         e.what());
          }
        });
  }

  float getX() const { return x; }
  float getY() const { return y; }
  float getZ() const { return z; }

  void updatePosition(float new_x, float new_y, float new_z) {
    x = new_x;
    y = new_y;
    z = new_z;
    updateLabels();
  }

  void updateLabels() {
    if (xLabel) xLabel->setText(QString("X: %1").arg(x, 0, 'f', 2));
    if (yLabel) yLabel->setText(QString("Y: %1").arg(y, 0, 'f', 2));
    if (zLabel) zLabel->setText(QString("Z: %1").arg(z, 0, 'f', 2));

    if (statusLabel) {
      float distance = std::sqrt(x * x + y * y + z * z);
      statusLabel->setText(QString("Status: Aktivan | Udaljenost od centra: %1")
                               .arg(distance, 0, 'f', 2));
    }
  }

  void publishVelocity(double vx, double vy, double vz) {
    auto msg = geometry_msgs::msg::Twist();
    msg.linear.x = vx;
    msg.linear.y = vy;
    msg.linear.z = vz;
    msg.angular.x = 0.0;
    msg.angular.y = 0.0;
    msg.angular.z = 0.0;

    cmd_vel_pub_->publish(msg);

    RCLCPP_DEBUG(ros_node_->get_logger(),
                 "Published velocity: vx=%.2f, vy=%.2f, vz=%.2f", vx, vy, vz);
  }

 protected:
  void keyPressEvent(QKeyEvent* event) override {
    const float step = 0.5f;
    double vx = 0.0, vy = 0.0, vz = 0.0;
    bool movement = false;

    switch (event->key()) {
      case Qt::Key_W:
      case Qt::Key_Up:
        vz = step * 10.0;  // Multiply for velocity
        z += step;
        movement = true;
        break;
      case Qt::Key_S:
      case Qt::Key_Down:
        vz = -step * 10.0;
        z -= step;
        movement = true;
        break;
      case Qt::Key_A:
      case Qt::Key_Left:
        vx = -step * 10.0;
        x -= step;
        movement = true;
        break;
      case Qt::Key_D:
      case Qt::Key_Right:
        vx = step * 10.0;
        x += step;
        movement = true;
        break;
      case Qt::Key_Q:
        vy = step * 10.0;
        y += step;
        movement = true;
        break;
      case Qt::Key_E:
        vy = -step * 10.0;
        y -= step;
        movement = true;
        break;
      case Qt::Key_R:
        // Reset position
        x = y = z = 0.0f;
        publishVelocity(0.0, 0.0, 0.0);
        RCLCPP_INFO(ros_node_->get_logger(), "Position reset to origin");
        break;
      case Qt::Key_Plus:
      case Qt::Key_Equal:
        scale += 5.0f;
        break;
      case Qt::Key_Minus:
        scale = std::max(10.0f, scale - 5.0f);
        break;
    }

    if (movement) {
      publishVelocity(vx, vy, vz);
    }

    update();
    updateLabels();
  }

  void keyReleaseEvent(QKeyEvent* event) override {
    // Stop movement when key is released
    switch (event->key()) {
      case Qt::Key_W:
      case Qt::Key_S:
      case Qt::Key_A:
      case Qt::Key_D:
      case Qt::Key_Q:
      case Qt::Key_E:
      case Qt::Key_Up:
      case Qt::Key_Down:
      case Qt::Key_Left:
      case Qt::Key_Right:
        publishVelocity(0.0, 0.0, 0.0);
        break;
    }
  }

  void paintEvent(QPaintEvent*) override {
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);

    // Background
    painter.fillRect(rect(), QColor(240, 245, 250));

    int centerX = width() / 2;
    int centerY = height() / 2;

    // Draw coordinate axes
    drawAxes(painter, centerX, centerY);

    // Draw grid
    drawGrid(painter, centerX, centerY);

    // Draw robot
    drawRobot(painter, centerX, centerY);

    // Display coordinates
    painter.setPen(Qt::black);
    painter.setFont(QFont("Arial", 12, QFont::Bold));
    painter.drawText(10, 30, QString("Pozicija robota:"));
    painter.drawText(10, 50, QString("X: %1").arg(x, 0, 'f', 2));
    painter.drawText(10, 70, QString("Y: %1").arg(y, 0, 'f', 2));
    painter.drawText(10, 90, QString("Z: %1").arg(z, 0, 'f', 2));

    // Controls info
    painter.setFont(QFont("Arial", 10));
    painter.drawText(10, height() - 100, "ROS2 Kontrole:");
    painter.drawText(10, height() - 80, "WASD / Strelice: Kreće X/Z");
    painter.drawText(10, height() - 60, "Q/E: Gore/Dole (Y)");
    painter.drawText(10, height() - 40, "R: Reset | +/-: Zoom");
    painter.drawText(10, height() - 20, "Publish na: /cmd_vel");
  }

  void drawAxes(QPainter& painter, int cx, int cy) {
    // X axis (red)
    painter.setPen(QPen(Qt::red, 2));
    QPointF xStart = project3D(-10, 0, 0, cx, cy);
    QPointF xEnd = project3D(10, 0, 0, cx, cy);
    painter.drawLine(xStart, xEnd);
    painter.drawText(xEnd, "X");

    // Y axis (green)
    painter.setPen(QPen(Qt::green, 2));
    QPointF yStart = project3D(0, -10, 0, cx, cy);
    QPointF yEnd = project3D(0, 10, 0, cx, cy);
    painter.drawLine(yStart, yEnd);
    painter.drawText(yEnd, "Y");

    // Z axis (blue)
    painter.setPen(QPen(Qt::blue, 2));
    QPointF zStart = project3D(0, 0, -10, cx, cy);
    QPointF zEnd = project3D(0, 0, 10, cx, cy);
    painter.drawLine(zStart, zEnd);
    painter.drawText(zEnd, "Z");
  }

  void drawGrid(QPainter& painter, int cx, int cy) {
    painter.setPen(QPen(QColor(200, 200, 200), 1, Qt::DotLine));

    for (int i = -10; i <= 10; i++) {
      if (i == 0) continue;

      // Grid on XZ plane (floor)
      QPointF p1 = project3D(i, 0, -10, cx, cy);
      QPointF p2 = project3D(i, 0, 10, cx, cy);
      painter.drawLine(p1, p2);

      QPointF p3 = project3D(-10, 0, i, cx, cy);
      QPointF p4 = project3D(10, 0, i, cx, cy);
      painter.drawLine(p3, p4);
    }
  }

  void drawRobot(QPainter& painter, int cx, int cy) {
    // Robot consists of body (cube) and head (sphere)

    // Robot body - cube
    float bodySize = 1.0f;
    QVector<QPointF> bodyPoints = {
        project3D(x - bodySize, y - bodySize, z - bodySize, cx, cy),  // 0
        project3D(x + bodySize, y - bodySize, z - bodySize, cx, cy),  // 1
        project3D(x + bodySize, y + bodySize, z - bodySize, cx, cy),  // 2
        project3D(x - bodySize, y + bodySize, z - bodySize, cx, cy),  // 3
        project3D(x - bodySize, y - bodySize, z + bodySize, cx, cy),  // 4
        project3D(x + bodySize, y - bodySize, z + bodySize, cx, cy),  // 5
        project3D(x + bodySize, y + bodySize, z + bodySize, cx, cy),  // 6
        project3D(x - bodySize, y + bodySize, z + bodySize, cx, cy)   // 7
    };

    // Draw cube edges
    painter.setPen(QPen(Qt::black, 3));
    painter.setBrush(QColor(100, 150, 250, 150));

    // Front face
    QPolygonF front;
    front << bodyPoints[4] << bodyPoints[5] << bodyPoints[6] << bodyPoints[7];
    painter.drawPolygon(front);

    // Top face
    painter.setBrush(QColor(120, 170, 255, 150));
    QPolygonF top;
    top << bodyPoints[3] << bodyPoints[2] << bodyPoints[6] << bodyPoints[7];
    painter.drawPolygon(top);

    // Right face
    painter.setBrush(QColor(80, 130, 230, 150));
    QPolygonF right;
    right << bodyPoints[1] << bodyPoints[2] << bodyPoints[6] << bodyPoints[5];
    painter.drawPolygon(right);

    // Robot head - circle
    float headY = y + bodySize + 0.7f;
    QPointF headCenter = project3D(x, headY, z, cx, cy);
    painter.setBrush(QColor(255, 200, 100));
    painter.drawEllipse(headCenter, scale * 0.5f, scale * 0.5f);

    // Eyes
    painter.setBrush(Qt::black);
    QPointF leftEye = project3D(x - 0.3f, headY, z + 0.3f, cx, cy);
    QPointF rightEye = project3D(x + 0.3f, headY, z + 0.3f, cx, cy);
    painter.drawEllipse(leftEye, scale * 0.1f, scale * 0.1f);
    painter.drawEllipse(rightEye, scale * 0.1f, scale * 0.1f);

    // Arms
    painter.setPen(QPen(Qt::darkGray, 4, Qt::SolidLine, Qt::RoundCap));
    QPointF leftArmStart = project3D(x - bodySize, y, z, cx, cy);
    QPointF leftArmEnd = project3D(x - bodySize - 0.8f, y - 0.8f, z, cx, cy);
    painter.drawLine(leftArmStart, leftArmEnd);

    QPointF rightArmStart = project3D(x + bodySize, y, z, cx, cy);
    QPointF rightArmEnd = project3D(x + bodySize + 0.8f, y - 0.8f, z, cx, cy);
    painter.drawLine(rightArmStart, rightArmEnd);

    // Floor position marker
    painter.setPen(QPen(Qt::red, 2, Qt::DashLine));
    painter.setBrush(Qt::NoBrush);
    QPointF groundPos = project3D(x, -2.0f, z, cx, cy);
    painter.drawEllipse(groundPos, scale * 0.3f, scale * 0.15f);
  }

  QPointF project3D(float px, float py, float pz, int cx, int cy) {
    // Isometric projection with rotation
    float rx = rotationX * M_PI / 180.0f;
    float ry = rotationY * M_PI / 180.0f;

    // Rotation around Y axis
    float x1 = px * cos(ry) + pz * sin(ry);
    float z1 = -px * sin(ry) + pz * cos(ry);
    float y1 = py;

    // Rotation around X axis
    float y2 = y1 * cos(rx) - z1 * sin(rx);
    float z2 = y1 * sin(rx) + z1 * cos(rx);
    float x2 = x1;

    // Screen projection
    float screenX = cx + x2 * scale;
    float screenY = cy - y2 * scale;

    return QPointF(screenX, screenY);
  }
};

class MainWindow : public QMainWindow {
 private:
  Robot3DWidget* robotWidget;
  QLabel* statusLabel;
  QLabel* xLabel;
  QLabel* yLabel;
  QLabel* zLabel;
  QLabel* handImageLabel;
  std::shared_ptr<rclcpp::Node> ros_node_;
  QTimer* ros_timer_;

 public:
  MainWindow(std::shared_ptr<rclcpp::Node> node, QWidget* parent = nullptr)
      : QMainWindow(parent), ros_node_(node) {
    setWindowTitle("🤖 SOCA - ROS2 Robot Visualizer");
    setMinimumSize(1000, 750);

    QWidget* centralWidget = new QWidget(this);
    QHBoxLayout* mainLayout = new QHBoxLayout(centralWidget);

    // Left panel - 3D visualization
    QWidget* leftPanel = new QWidget(this);
    QVBoxLayout* leftLayout = new QVBoxLayout(leftPanel);

    // Title
    QLabel* titleLabel = new QLabel("ROS2 Robot Visualizer (Humble)", this);
    titleLabel->setAlignment(Qt::AlignCenter);
    titleLabel->setStyleSheet(
        "font-size: 24px; font-weight: bold; color: #2c3e50; padding: 10px;");
    leftLayout->addWidget(titleLabel);

    // Status panel
    QWidget* statusPanel = new QWidget(this);
    QHBoxLayout* statusLayout = new QHBoxLayout(statusPanel);
    statusPanel->setStyleSheet(
        "background-color: #ecf0f1; padding: 10px; border-radius: 5px;");

    statusLabel = new QLabel("Status: ROS2 Connected", this);
    statusLabel->setStyleSheet(
        "font-size: 14px; font-weight: bold; color: #27ae60;");

    xLabel = new QLabel("X: 0.00", this);
    yLabel = new QLabel("Y: 0.00", this);
    zLabel = new QLabel("Z: 0.00", this);

    xLabel->setStyleSheet(
        "font-size: 14px; color: #e74c3c; font-weight: bold;");
    yLabel->setStyleSheet(
        "font-size: 14px; color: #27ae60; font-weight: bold;");
    zLabel->setStyleSheet(
        "font-size: 14px; color: #3498db; font-weight: bold;");

    statusLayout->addWidget(statusLabel);
    statusLayout->addStretch();
    statusLayout->addWidget(xLabel);
    statusLayout->addWidget(yLabel);
    statusLayout->addWidget(zLabel);

    leftLayout->addWidget(statusPanel);

    // 3D widget
    handImageLabel = new QLabel(this);
    handImageLabel->setStyleSheet(
        "background-color: black; border: 2px solid #3498db;");
    handImageLabel->setAlignment(Qt::AlignCenter);
    handImageLabel->setMinimumSize(320, 240);
    handImageLabel->setMaximumSize(320, 240);
    handImageLabel->setText("Čekam hand tracking sliku...");
    handImageLabel->setStyleSheet(
        "background-color: #2c3e50; color: white; font-size: 12px; border: 2px "
        "solid #3498db; border-radius: 5px;");

    robotWidget = new Robot3DWidget(xLabel, yLabel, zLabel, statusLabel,
                                    handImageLabel, ros_node_, this);
    leftLayout->addWidget(robotWidget);

    // Control buttons
    QWidget* controlPanel = new QWidget(this);
    QHBoxLayout* controlLayout = new QHBoxLayout(controlPanel);

    QPushButton* resetBtn = new QPushButton("🔄 Reset Poziciju", this);
    QPushButton* upBtn = new QPushButton("⬆️ Gore (Q)", this);
    QPushButton* downBtn = new QPushButton("⬇️ Dole (E)", this);

    resetBtn->setStyleSheet("font-size: 14px; padding: 10px;");
    upBtn->setStyleSheet("font-size: 14px; padding: 10px;");
    downBtn->setStyleSheet("font-size: 14px; padding: 10px;");

    connect(resetBtn, &QPushButton::clicked, this, [this]() {
      QKeyEvent* event =
          new QKeyEvent(QEvent::KeyPress, Qt::Key_R, Qt::NoModifier);
      QApplication::postEvent(robotWidget, event);
    });

    connect(upBtn, &QPushButton::clicked, this, [this]() {
      QKeyEvent* event =
          new QKeyEvent(QEvent::KeyPress, Qt::Key_Q, Qt::NoModifier);
      QApplication::postEvent(robotWidget, event);
    });

    connect(downBtn, &QPushButton::clicked, this, [this]() {
      QKeyEvent* event =
          new QKeyEvent(QEvent::KeyPress, Qt::Key_E, Qt::NoModifier);
      QApplication::postEvent(robotWidget, event);
    });

    controlLayout->addWidget(resetBtn);
    controlLayout->addWidget(upBtn);
    controlLayout->addWidget(downBtn);

    leftLayout->addWidget(controlPanel);

    // Right panel - Hand tracking camera feed
    QWidget* rightPanel = new QWidget(this);
    QVBoxLayout* rightLayout = new QVBoxLayout(rightPanel);

    QLabel* cameraTitle = new QLabel("👋 Hand Tracking Camera", this);
    cameraTitle->setAlignment(Qt::AlignCenter);
    cameraTitle->setStyleSheet(
        "font-size: 18px; font-weight: bold; color: #2c3e50; padding: 10px;");
    rightLayout->addWidget(cameraTitle);

    rightLayout->addWidget(handImageLabel);

    QLabel* instructionsLabel = new QLabel(
        "🎮 Kontrole:\n\n"
        "• Pomeri ruku LEVO/DESNO\n"
        "  → Robot X osa\n\n"
        "• Pomeri ruku GORE/DOLE\n"
        "  → Robot Z osa\n\n"
        "• Pomeri ruku BLIŽE/DALJE\n"
        "  → Robot Y osa (visina)",
        this);
    instructionsLabel->setStyleSheet(
        "background-color: #ecf0f1; padding: 15px; border-radius: 5px; "
        "font-size: 13px; color: #2c3e50;");
    instructionsLabel->setWordWrap(true);
    rightLayout->addWidget(instructionsLabel);

    rightLayout->addStretch();

    // Add panels to main layout
    mainLayout->addWidget(leftPanel, 2);
    mainLayout->addWidget(rightPanel, 1);

    setCentralWidget(centralWidget);

    // Setup ROS2 timer for spinning
    ros_timer_ = new QTimer(this);
    connect(ros_timer_, &QTimer::timeout, this,
            [this]() { rclcpp::spin_some(ros_node_); });
    ros_timer_->start(10);  // Spin every 10ms
  }
};

int main(int argc, char* argv[]) {
  // Initialize ROS2
  rclcpp::init(argc, argv);

  // Create ROS2 node
  auto node = std::make_shared<rclcpp::Node>("robot_visualizer");

  RCLCPP_INFO(node->get_logger(),
              "===========================================");
  RCLCPP_INFO(node->get_logger(), "  🤖 SOCA Robot Visualizer ROS2 Humble");
  RCLCPP_INFO(node->get_logger(),
              "===========================================");
  RCLCPP_INFO(node->get_logger(), "Publishing to /cmd_vel");
  RCLCPP_INFO(node->get_logger(), "Use WASD/Arrow keys to move robot");

  // Initialize Qt
  QApplication app(argc, argv);

  MainWindow window(node);
  window.show();

  int result = app.exec();

  rclcpp::shutdown();
  return result;
}
