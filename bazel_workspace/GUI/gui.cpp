#include <QApplication>
#include <QDesktopServices>
#include <QInputDialog>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QUrl>
#include <QVBoxLayout>
#include <QWidget>

int main(int argc, char *argv[]) {
  QApplication app(argc, argv);

  // Create main window
  QWidget window;
  window.setWindowTitle("SOCA - Web Browser Launcher");
  window.setMinimumSize(400, 250);

  // Create layout
  QVBoxLayout *layout = new QVBoxLayout(&window);

  // Create title label
  QLabel *titleLabel = new QLabel("🚀 SOCA Web Browser Launcher");
  titleLabel->setAlignment(Qt::AlignCenter);
  titleLabel->setStyleSheet(
      "font-size: 16px; font-weight: bold; color: #2E86C1;");
  layout->addWidget(titleLabel);

  // Create subtitle
  QLabel *subtitleLabel = new QLabel("Izaberite web stranicu za otvaranje:");
  subtitleLabel->setAlignment(Qt::AlignCenter);
  layout->addWidget(subtitleLabel);

  // Create buttons
  QPushButton *githubButton = new QPushButton("📖 Otvori GitHub projekat");
  QPushButton *googleButton = new QPushButton("🔍 Otvori Google");
  QPushButton *localButton = new QPushButton("🏠 Otvori lokalni server");
  QPushButton *customButton = new QPushButton("🌐 Otvori custom URL");

  layout->addWidget(githubButton);
  layout->addWidget(googleButton);
  layout->addWidget(localButton);
  layout->addWidget(customButton);

  // Create status label
  QLabel *statusLabel = new QLabel("Status: Spreman");
  statusLabel->setAlignment(Qt::AlignCenter);
  statusLabel->setStyleSheet("color: #28B463;");
  layout->addWidget(statusLabel);

  // Connect button signals
  QObject::connect(githubButton, &QPushButton::clicked, [&]() {
    if (QDesktopServices::openUrl(
            QUrl("https://github.com/ministar016/soca"))) {
      statusLabel->setText("✅ GitHub otvoren!");
      statusLabel->setStyleSheet("color: #28B463;");
    } else {
      statusLabel->setText("❌ Greška pri otvaranju!");
      statusLabel->setStyleSheet("color: #E74C3C;");
    }
  });

  QObject::connect(googleButton, &QPushButton::clicked, [&]() {
    if (QDesktopServices::openUrl(QUrl("https://www.google.com"))) {
      statusLabel->setText("✅ Google otvoren!");
      statusLabel->setStyleSheet("color: #28B463;");
    } else {
      statusLabel->setText("❌ Greška pri otvaranju!");
      statusLabel->setStyleSheet("color: #E74C3C;");
    }
  });

  QObject::connect(localButton, &QPushButton::clicked, [&]() {
    if (QDesktopServices::openUrl(QUrl("http://localhost:8000"))) {
      statusLabel->setText("✅ Lokalni server otvoren!");
      statusLabel->setStyleSheet("color: #28B463;");
    } else {
      statusLabel->setText("❌ Greška pri otvaranju!");
      statusLabel->setStyleSheet("color: #E74C3C;");
    }
  });

  QObject::connect(customButton, &QPushButton::clicked, [&]() {
    bool ok;
    QString url = QInputDialog::getText(&window, "Custom URL",
                                        "Unesite URL:", QLineEdit::Normal,
                                        "https://", &ok);
    if (ok && !url.isEmpty()) {
      // Dodaj https:// ako nije naveden
      if (!url.startsWith("http://") && !url.startsWith("https://")) {
        url = "https://" + url;
      }

      if (QDesktopServices::openUrl(QUrl(url))) {
        statusLabel->setText("✅ Custom URL otvoren!");
        statusLabel->setStyleSheet("color: #28B463;");
      } else {
        statusLabel->setText("❌ Greška pri otvaranju URL-a!");
        statusLabel->setStyleSheet("color: #E74C3C;");
      }
    }
  });

  window.show();

  return app.exec();
}
