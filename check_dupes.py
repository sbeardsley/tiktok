def check_duplicates(filename):
    with open(filename, "r") as f:
        usernames = [line.strip() for line in f if line.strip()]

    # Convert to set and back to list to find duplicates
    unique_usernames = set(usernames)
    duplicates = [name for name in usernames if usernames.count(name) > 1]

    # Get unique duplicates
    unique_duplicates = set(duplicates)

    if unique_duplicates:
        print("\nFound duplicate usernames:")
        for name in unique_duplicates:
            print(f"- {name} (appears {usernames.count(name)} times)")
        print(f"\nTotal unique usernames: {len(unique_usernames)}")
        print(f"Total usernames including duplicates: {len(usernames)}")
    else:
        print("\nNo duplicates found!")
        print(f"Total unique usernames: {len(usernames)}")


check_duplicates("usernames.md")
