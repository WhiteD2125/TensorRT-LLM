def install_command(dotfiles_path):
    """
    Install the dotfiles command.

    Args:
        dotfiles_path (str): The path to the dotfiles directory.

    Returns:
        None
    """
    # Check if the dotfiles directory exists
    if not os.path.exists(dotfiles_path):
        print(f"Error: Dotfiles directory '{dotfiles_path}' does not exist.")
        return

    # Create the dotfiles command
    dotfiles_command = f"{dotfiles_path}/dotfiles.sh"

    # Check if the dotfiles command exists
    if not os.path.exists(dotfiles_command):
        print(f"Error: Dotfiles command '{dotfiles_command}' does not exist.")
        return

    # Add the dotfiles command to the system PATH
    os.environ["PATH"] += f":{dotfiles_path}"

    # Print a success message
    print(f"Dotfiles command '{dotfiles_command}' installed successfully.")