import { useStats } from '../hooks/useStats';
import { useGroups } from '../hooks/useGroups';
import { formatRelativeTime, anonymizeGroupId } from '../lib/utils';

export default function Dashboard() {
  const { pending, runs, isLoading } = useStats();
  const { groups } = useGroups();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center py-12 text-gray-600 dark:text-gray-400">
          Loading dashboard...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
        Dashboard
      </h1>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatsCard
          title="Pending Messages"
          value={pending?.total_messages || 0}
          subtitle="awaiting summary"
          icon="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
        />
        <StatsCard
          title="Groups"
          value={groups.length}
          subtitle="synced from Signal"
          icon="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
        />
        <StatsCard
          title="Recent Runs"
          value={runs.filter(r => r.status === 'completed').length}
          subtitle={`of ${runs.length} total`}
          icon="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
        />
        <StatsCard
          title="Failed Runs"
          value={runs.filter(r => r.status === 'failed').length}
          subtitle="need attention"
          icon="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
          variant={runs.filter(r => r.status === 'failed').length > 0 ? 'warning' : 'default'}
        />
      </div>

      {/* Pending by Group */}
      {pending?.messages_by_group && Object.keys(pending.messages_by_group).length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white">
            Pending Messages by Group
          </h2>
          <div className="space-y-3">
            {Object.entries(pending.messages_by_group).map(([groupId, count]) => {
              return (
                <div key={groupId} className="flex items-center justify-between">
                  <span className="text-gray-700 dark:text-gray-300 font-mono">
                    {anonymizeGroupId(groupId)}
                  </span>
                  <span className="px-2 py-1 bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 rounded text-sm font-medium">
                    {count} messages
                  </span>
                </div>
              );
            })}
          </div>
          {pending.oldest_message && (
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">
              Oldest message: {formatRelativeTime(pending.oldest_message)}
            </p>
          )}
        </div>
      )}

      {/* Recent Summary Runs */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-white">
          Recent Summary Runs
        </h2>
        {runs.length === 0 ? (
          <p className="text-gray-500 dark:text-gray-400">No summary runs yet.</p>
        ) : (
          <div className="space-y-3">
            {runs.slice(0, 10).map((run) => (
              <div
                key={run.id}
                className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700 rounded-lg"
              >
                <div>
                  <p className="font-medium text-gray-900 dark:text-white">
                    {run.schedule_name || `Schedule #${run.schedule_id}`}
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    {formatRelativeTime(run.started_at)} - {run.message_count} messages
                  </p>
                </div>
                <StatusBadge status={run.status} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatsCard({
  title,
  value,
  subtitle,
  icon,
  variant = 'default',
}: {
  title: string;
  value: number;
  subtitle?: string;
  icon: string;
  variant?: 'default' | 'warning';
}) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
      <div className="flex items-center gap-4">
        <div className={`p-3 rounded-lg ${
          variant === 'warning' && value > 0
            ? 'bg-yellow-100 dark:bg-yellow-900'
            : 'bg-blue-100 dark:bg-blue-900'
        }`}>
          <svg
            className={`w-6 h-6 ${
              variant === 'warning' && value > 0
                ? 'text-yellow-600 dark:text-yellow-400'
                : 'text-blue-600 dark:text-blue-400'
            }`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={icon} />
          </svg>
        </div>
        <div>
          <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400">{title}</h3>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">
            {value.toLocaleString()}
          </p>
          {subtitle && (
            <p className="text-xs text-gray-500 dark:text-gray-400">{subtitle}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles = {
    completed: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
    failed: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  };

  return (
    <span className={`px-2 py-1 rounded text-xs font-medium ${styles[status as keyof typeof styles] || styles.pending}`}>
      {status}
    </span>
  );
}
