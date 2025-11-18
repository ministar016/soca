cc_binary(
    name = "gui_app",
    srcs = ["gui.cpp"],
    copts = [
        "-fPIC",
        "-std=c++17",
        "-isystem/usr/include/x86_64-linux-gnu/qt6",
        "-isystem/usr/include/x86_64-linux-gnu/qt6/QtWidgets",
        "-isystem/usr/include/x86_64-linux-gnu/qt6/QtCore",
        "-isystem/usr/include/x86_64-linux-gnu/qt6/QtGui",
        "-DQT_WIDGETS_LIB",
        "-DQT_GUI_LIB",
        "-DQT_CORE_LIB",
    ],
    linkopts = [
        "-lQt6Widgets",
        "-lQt6Core",
        "-lQt6Gui",
    ],
    visibility = ["//visibility:public"],
)

# Temporarily commented out until gui_lib files are created
# cc_library(
#     name = "gui_lib",
#     srcs = ["gui_lib.cpp"],
#     hdrs = ["gui_lib.h"],
#     deps = [
#         "//third_party/some_gui_library",
#     ],
#     visibility = ["//visibility:public"],
# )
