"""Train the 9-player No-Limit Hold'em 1/2 bot by self-play MCCFR.

  python train.py --iterations 200000                # fresh run, all cores
  python train.py --iterations 100000 --resume       # continue from the checkpoint
"""

import argparse
import os
import time

import mccfr
from evaluate import baseline_report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=200_000, help="self-play hands to train on")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--epoch", type=int, default=250, help="iterations per worker per epoch")
    ap.add_argument("--models", default="models")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--eval-every", type=int, default=50_000, help="0 disables periodic eval")
    ap.add_argument("--eval-decks", type=int, default=40)
    ap.add_argument("--save-every", type=int, default=500_000,
                    help="checkpoint interval, so an interrupted run can --resume")
    ap.add_argument("--snapshots", default="2000,20000",
                    help="iteration counts at which to save a policy snapshot")
    ap.add_argument("--stack-range", default=None,
                    help="random stack sizes per seat, e.g. 60-240 (default: everyone 200)")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    os.makedirs(os.path.join(args.models, "snapshots"), exist_ok=True)
    ckpt = os.path.join(args.models, "nlhe9_checkpoint.pkl")
    policy = os.path.join(args.models, "nlhe9_policy.pkl")
    snapshots = sorted(int(x) for x in args.snapshots.split(",") if x)

    if args.stack_range:
        lo, hi = (int(x) for x in args.stack_range.split("-"))
        mccfr.STACK_RANGE = (lo, hi)
    trainer = mccfr.Trainer(args.workers, args.epoch, args.seed)
    if args.resume and os.path.exists(ckpt):
        trainer.load_checkpoint(ckpt)
        print(f"Resumed from {ckpt} at iteration {trainer.iterations:,}")
    target = trainer.iterations + args.iterations
    print(f"Training to {target:,} iterations with {args.workers} workers...")

    start = time.time()
    start_iter = trainer.iterations
    next_eval = trainer.iterations + args.eval_every if args.eval_every else None
    next_save = trainer.iterations + args.save_every
    last_print = 0.0
    while trainer.iterations < target:
        trainer.train_epoch()
        it = trainer.iterations
        while snapshots and it >= snapshots[0]:
            path = os.path.join(args.models, "snapshots", f"policy_iter_{snapshots[0]}.pkl")
            mccfr.export_policy(path, it)
            print(f"  snapshot saved: {path}")
            snapshots.pop(0)
        now = time.time()
        if now - last_print > 15 or it >= target:
            rate = (it - start_iter) / (now - start)
            print(f"  iter {it:>9,}  |  {rate:7.0f} it/s  |  infosets {len(mccfr.TABLE):>9,}  |  "
                  f"{(now - start) / 60:5.1f} min", flush=True)
            last_print = now
        if it >= next_save and it < target:
            trainer.save_checkpoint(ckpt)
            mccfr.export_policy(policy, it)
            next_save += args.save_every
        if next_eval and it >= next_eval:
            mccfr.export_policy(policy, it)
            print(f"  eval @ {it:,} iterations:")
            baseline_report(policy, args.eval_decks, out=lambda s: print(s, flush=True))
            next_eval += args.eval_every

    trainer.save_checkpoint(ckpt)
    n = mccfr.export_policy(policy, trainer.iterations)
    print(f"Done: {trainer.iterations:,} iterations in {(time.time() - start) / 60:.1f} min, "
          f"{n:,} infosets in policy -> {policy}")


if __name__ == "__main__":
    main()
