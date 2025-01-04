# redis_backup.py
This script provides:
1. Backup functionality:
- Compresses backups (optional)
- Includes all metadata, sets, and relationships
- Timestamps backups
- Shows progress with tqdm
2. Restore functionality:
- Can restore from compressed or uncompressed backups
- Option to clear existing data
- Maintains all relationships
- Progress indicators
3. Management features:
- List available backups
- Cleanup old backups
- Interactive menu
- Detailed logging
## To use:
```
python services/redis_backup.py
```
Would you like me to:
Add scheduled automatic backups?
Add backup verification?
Add differential backups?
Add backup encryption?
