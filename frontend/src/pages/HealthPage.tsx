import { useQuery } from '@tanstack/react-query';
import { fetchHealth, type HealthResponse } from '../api/health';

function StatusRow({ label, value, good }: { label: string; value: string; good?: string }) {
  const isGood = good === undefined || value === good;
  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-800 last:border-0">
      <span className="text-sm text-gray-400">{label}</span>
      <div className="flex items-center gap-2">
        {good !== undefined && (
          <span
            className={`inline-block w-2 h-2 rounded-full ${isGood ? 'bg-green-400' : 'bg-red-400'}`}
          />
        )}
        <span
          className={`text-sm font-mono font-medium ${
            good === undefined ? 'text-gray-300' : isGood ? 'text-green-400' : 'text-red-400'
          }`}
        >
          {value}
        </span>
      </div>
    </div>
  );
}

export function HealthPage() {
  const { data, isLoading, isError, error, dataUpdatedAt } = useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
  });

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex items-center justify-center p-4">
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-8 w-full max-w-sm shadow-2xl">
        {/* Logo / title */}
        <div className="flex items-center gap-3 mb-8">
          <div className="w-9 h-9 rounded-lg bg-indigo-600 flex items-center justify-center shrink-0">
            <span className="text-white font-bold text-base">V</span>
          </div>
          <div>
            <h1 className="font-semibold text-lg leading-none">Veridian</h1>
            <p className="text-xs text-gray-500 mt-0.5">RAG Platform</p>
          </div>
        </div>

        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-4">
          System Health
        </h2>

        {/* Loading */}
        {isLoading && (
          <div className="flex items-center gap-2 text-gray-400 py-4">
            <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
            <span className="text-sm">Contacting backend…</span>
          </div>
        )}

        {/* Error */}
        {isError && (
          <div className="rounded-lg bg-red-950/50 border border-red-900 p-3 text-sm text-red-400">
            <p className="font-medium">Backend unreachable</p>
            <p className="mt-1 text-xs opacity-70">{String(error)}</p>
          </div>
        )}

        {/* Data */}
        {data && (
          <div>
            <StatusRow label="API Status" value={data.status} good="ok" />
            <StatusRow label="Database" value={data.database} good="connected" />
            <StatusRow label="Version" value={`v${data.version}`} />
          </div>
        )}

        {/* Last updated */}
        {dataUpdatedAt > 0 && (
          <p className="mt-4 text-xs text-gray-600">
            Last checked: {new Date(dataUpdatedAt).toLocaleTimeString()}
          </p>
        )}
      </div>
    </div>
  );
}
