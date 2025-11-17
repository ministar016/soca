cc_library(
    name = "hello_world",
    srcs = ["hello_world.cpp"],
    hdrs = ["hello_world.h"],
    visibility = ["//visibility:public"],
)

cc_test(
    name = "hello_world_test",
    srcs = ["test.cpp"],
    deps = [":hello_world"],
)
