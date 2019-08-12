import sys

from .database import BotDatabase

def main(argv):
    if len(argv) != 3:
        print('usage: merge_db.py <dest_db> <src_db>', file=sys.stderr)
        return 1
    db = BotDatabase(argv[1])
    db.merge(argv[2])
    db.save()
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
