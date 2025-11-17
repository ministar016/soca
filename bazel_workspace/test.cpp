#include <cassert>
#include <iostream>

#include "hello_world.h"

int main() {
  // Test the getMessage function
  std::string message = HelloWorld::getMessage();
  std::cout << "Testing HelloWorld::getMessage(): " << message << std::endl;
  assert(message == "Hello, World from Bazel!");

  // Test the printMessage function
  std::cout << "Testing HelloWorld::printMessage(): ";
  HelloWorld::printMessage();

  std::cout << "All tests passed!" << std::endl;
  return 0;
}
