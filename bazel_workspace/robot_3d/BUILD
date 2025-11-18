load("@rules_cc//cc:defs.bzl", "cc_binary")

cc_binary(
    name = "robot_3d",
    srcs = ["robot_3d.cpp"],
    copts = [
        "-fPIC",
        "-DQT_WIDGETS_LIB",
        "-DQT_GUI_LIB",
        "-DQT_CORE_LIB",
        "-I/usr/include/x86_64-linux-gnu/qt6",
        "-I/usr/include/x86_64-linux-gnu/qt6/QtWidgets",
        "-I/usr/include/x86_64-linux-gnu/qt6/QtGui",
        "-I/usr/include/x86_64-linux-gnu/qt6/QtCore",
    ],
    linkopts = [
        "-lQt6Widgets",
        "-lQt6Gui",
        "-lQt6Core",
        "-L/usr/lib/x86_64-linux-gnu",
    ],
    visibility = ["//visibility:public"],
)
