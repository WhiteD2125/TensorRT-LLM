import json
import os


def find_cmake_generator(cmake_path, kits_path):
    """
    Find a suitable CMake generator for the given CMake and Kit configurations.

    Args:
        cmake_path (str): The path to the CMake installation.
        kits_path (str): The path to the Kit configuration file.

    Returns:
        str: The path to the suitable CMake generator.
    """
    # Load the Kit configurations
    kits = load_kits(kits_path)

    # Iterate through the Kit configurations
    for kit in kits:
        # Check if the Kit is trusted
        if kit["trusted"]:
            # Get the Kit's GCC version and architecture
            gcc_version = kit["gcc_version"]
            gcc_arch = kit["gcc_arch"]

            # Construct the CMake generator path
            cmake_generator_path = f"{cmake_path}/bin/{gcc_version}_{gcc_arch}-cmake-generator"

            # Check if the CMake generator exists
            if os.path.exists(cmake_generator_path):
                return cmake_generator_path

    # If no suitable CMake generator is found, raise an error
    raise ValueError("No usable generator found.")


def load_kits(kits_path):
    """
    Load the Kit configurations from the given file path.

    Args:
        kits_path (str): The path to the Kit configuration file.

    Returns:
        list: A list of Kit configurations.
    """
    # Read the Kit configuration file
    with open(kits_path, "r") as file:
        kits_data = file.read()

    # Parse the Kit configuration file
    kits = json.loads(kits_data)

    return kits