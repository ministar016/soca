#include <QApplication>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QLabel>
#include <QMainWindow>
#include <QPainter>
#include <QPushButton>
#include <QTimer>
#include <QVBoxLayout>
#include <QWidget>
#include <cmath>

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

 public:
  Robot3DWidget(QLabel* xLbl, QLabel* yLbl, QLabel* zLbl, QLabel* statusLbl,
                QWidget* parent = nullptr)
      : QWidget(parent),
        xLabel(xLbl),
        yLabel(yLbl),
        zLabel(zLbl),
        statusLabel(statusLbl) {
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
  }

  float getX() const { return x; }
  float getY() const { return y; }
  float getZ() const { return z; }

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

 protected:
  void keyPressEvent(QKeyEvent* event) override {
    const float step = 0.5f;

    switch (event->key()) {
      case Qt::Key_W:
      case Qt::Key_Up:
        z += step;
        break;
      case Qt::Key_S:
      case Qt::Key_Down:
        z -= step;
        break;
      case Qt::Key_A:
      case Qt::Key_Left:
        x -= step;
        break;
      case Qt::Key_D:
      case Qt::Key_Right:
        x += step;
        break;
      case Qt::Key_Q:
        y += step;
        break;
      case Qt::Key_E:
        y -= step;
        break;
      case Qt::Key_R:
        // Reset pozicije
        x = y = z = 0.0f;
        break;
      case Qt::Key_Plus:
      case Qt::Key_Equal:
        scale += 5.0f;
        break;
      case Qt::Key_Minus:
        scale = std::max(10.0f, scale - 5.0f);
        break;
    }

    update();
    updateLabels();
  }

  void paintEvent(QPaintEvent*) override {
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);

    // Pozadina
    painter.fillRect(rect(), QColor(240, 245, 250));

    int centerX = width() / 2;
    int centerY = height() / 2;

    // Crtanje koordinatnih osa
    drawAxes(painter, centerX, centerY);

    // Crtanje grid-a
    drawGrid(painter, centerX, centerY);

    // Crtanje robota
    drawRobot(painter, centerX, centerY);

    // Ispis koordinata
    painter.setPen(Qt::black);
    painter.setFont(QFont("Arial", 12, QFont::Bold));
    painter.drawText(10, 30, QString("Pozicija robota:"));
    painter.drawText(10, 50, QString("X: %1").arg(x, 0, 'f', 2));
    painter.drawText(10, 70, QString("Y: %1").arg(y, 0, 'f', 2));
    painter.drawText(10, 90, QString("Z: %1").arg(z, 0, 'f', 2));

    // Kontrole
    painter.setFont(QFont("Arial", 10));
    painter.drawText(10, height() - 80, "Kontrole:");
    painter.drawText(10, height() - 60, "WASD / Strelice: Kreće X/Z");
    painter.drawText(10, height() - 40, "Q/E: Gore/Dole (Y)");
    painter.drawText(10, height() - 20, "R: Reset | +/-: Zoom");
  }

  void drawAxes(QPainter& painter, int cx, int cy) {
    // X osa (crvena)
    painter.setPen(QPen(Qt::red, 2));
    QPointF xStart = project3D(-10, 0, 0, cx, cy);
    QPointF xEnd = project3D(10, 0, 0, cx, cy);
    painter.drawLine(xStart, xEnd);
    painter.drawText(xEnd, "X");

    // Y osa (zelena)
    painter.setPen(QPen(Qt::green, 2));
    QPointF yStart = project3D(0, -10, 0, cx, cy);
    QPointF yEnd = project3D(0, 10, 0, cx, cy);
    painter.drawLine(yStart, yEnd);
    painter.drawText(yEnd, "Y");

    // Z osa (plava)
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

      // Grid na XZ ravni (podloga)
      QPointF p1 = project3D(i, 0, -10, cx, cy);
      QPointF p2 = project3D(i, 0, 10, cx, cy);
      painter.drawLine(p1, p2);

      QPointF p3 = project3D(-10, 0, i, cx, cy);
      QPointF p4 = project3D(10, 0, i, cx, cy);
      painter.drawLine(p3, p4);
    }
  }

  void drawRobot(QPainter& painter, int cx, int cy) {
    // Robot se sastoji od tela (kocka) i glave (sfera)

    // Telo robota - kocka
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

    // Crtanje ivica kocke
    painter.setPen(QPen(Qt::black, 3));
    painter.setBrush(QColor(100, 150, 250, 150));

    // Prednja strana
    QPolygonF front;
    front << bodyPoints[4] << bodyPoints[5] << bodyPoints[6] << bodyPoints[7];
    painter.drawPolygon(front);

    // Gornja strana
    painter.setBrush(QColor(120, 170, 255, 150));
    QPolygonF top;
    top << bodyPoints[3] << bodyPoints[2] << bodyPoints[6] << bodyPoints[7];
    painter.drawPolygon(top);

    // Desna strana
    painter.setBrush(QColor(80, 130, 230, 150));
    QPolygonF right;
    right << bodyPoints[1] << bodyPoints[2] << bodyPoints[6] << bodyPoints[5];
    painter.drawPolygon(right);

    // Glava robota - krug
    float headY = y + bodySize + 0.7f;
    QPointF headCenter = project3D(x, headY, z, cx, cy);
    painter.setBrush(QColor(255, 200, 100));
    painter.drawEllipse(headCenter, scale * 0.5f, scale * 0.5f);

    // Oči
    painter.setBrush(Qt::black);
    QPointF leftEye = project3D(x - 0.3f, headY, z + 0.3f, cx, cy);
    QPointF rightEye = project3D(x + 0.3f, headY, z + 0.3f, cx, cy);
    painter.drawEllipse(leftEye, scale * 0.1f, scale * 0.1f);
    painter.drawEllipse(rightEye, scale * 0.1f, scale * 0.1f);

    // Ruke
    painter.setPen(QPen(Qt::darkGray, 4, Qt::SolidLine, Qt::RoundCap));
    QPointF leftArmStart = project3D(x - bodySize, y, z, cx, cy);
    QPointF leftArmEnd = project3D(x - bodySize - 0.8f, y - 0.8f, z, cx, cy);
    painter.drawLine(leftArmStart, leftArmEnd);

    QPointF rightArmStart = project3D(x + bodySize, y, z, cx, cy);
    QPointF rightArmEnd = project3D(x + bodySize + 0.8f, y - 0.8f, z, cx, cy);
    painter.drawLine(rightArmStart, rightArmEnd);

    // Pozicija markera na podu
    painter.setPen(QPen(Qt::red, 2, Qt::DashLine));
    painter.setBrush(Qt::NoBrush);
    QPointF groundPos = project3D(x, -2.0f, z, cx, cy);
    painter.drawEllipse(groundPos, scale * 0.3f, scale * 0.15f);
  }

  QPointF project3D(float px, float py, float pz, int cx, int cy) {
    // Isometric projekcija sa rotacijom
    float rx = rotationX * M_PI / 180.0f;
    float ry = rotationY * M_PI / 180.0f;

    // Rotacija oko Y ose
    float x1 = px * cos(ry) + pz * sin(ry);
    float z1 = -px * sin(ry) + pz * cos(ry);
    float y1 = py;

    // Rotacija oko X ose
    float y2 = y1 * cos(rx) - z1 * sin(rx);
    float z2 = y1 * sin(rx) + z1 * cos(rx);
    float x2 = x1;

    // Projekcija na ekran
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

 public:
  MainWindow(QWidget* parent = nullptr) : QMainWindow(parent) {
    setWindowTitle("🤖 SOCA - 3D Robot Simulator");
    setMinimumSize(800, 700);

    QWidget* centralWidget = new QWidget(this);
    QVBoxLayout* mainLayout = new QVBoxLayout(centralWidget);

    // Naslov
    QLabel* titleLabel = new QLabel("3D Robot Simulator", this);
    titleLabel->setAlignment(Qt::AlignCenter);
    titleLabel->setStyleSheet(
        "font-size: 24px; font-weight: bold; color: #2c3e50; padding: 10px;");
    mainLayout->addWidget(titleLabel);

    // Status panel
    QWidget* statusPanel = new QWidget(this);
    QHBoxLayout* statusLayout = new QHBoxLayout(statusPanel);
    statusPanel->setStyleSheet(
        "background-color: #ecf0f1; padding: 10px; border-radius: 5px;");

    statusLabel = new QLabel("Status: Spreman", this);
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

    mainLayout->addWidget(statusPanel);

    // 3D widget - kreiramo nakon label-a
    robotWidget = new Robot3DWidget(xLabel, yLabel, zLabel, statusLabel, this);
    mainLayout->addWidget(robotWidget);

    // Dugmad za kontrolu
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

    mainLayout->addWidget(controlPanel);

    setCentralWidget(centralWidget);
  }
};

int main(int argc, char* argv[]) {
  QApplication app(argc, argv);

  MainWindow window;
  window.show();

  return app.exec();
}
