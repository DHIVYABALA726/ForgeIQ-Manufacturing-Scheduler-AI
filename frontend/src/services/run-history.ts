import type { ScheduleRun } from '../types';

/** Reconcile every saved-run badge against the dataset version returned by the backend. */
export function reconcileScheduleRuns(current: ScheduleRun[], next: ScheduleRun): ScheduleRun[] {
  const version = next.current_dataset_version;
  const activeRun: ScheduleRun = {
    ...next,
    current_dataset_version: version,
    is_stale: next.dataset_version !== version,
  };
  const previousRuns = current
    .filter(item => item.id !== next.id)
    .map(item => ({
      ...item,
      current_dataset_version: version,
      is_stale: item.dataset_version !== version,
    }));
  return [activeRun, ...previousRuns];
}
