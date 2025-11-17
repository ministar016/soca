#include "hello_world.h"

#include <iostream>

std::string HelloWorld::getMessage() { return "Hello, World from Bazel!"; }

void HelloWorld::printMessage() { std::cout << getMessage() << std::endl; }
