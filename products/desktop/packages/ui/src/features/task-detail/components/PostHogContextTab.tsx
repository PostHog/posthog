interface PostHogContextTabProps {
  body: string;
}

export function PostHogContextTab({ body }: PostHogContextTabProps) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="p-4">
        <p className="mb-3 text-[12px] text-gray-9">
          Sent with this message from PostHog, exactly as the agent received it.
        </p>
        <pre className="whitespace-pre-wrap break-words rounded-md border border-gray-6 bg-gray-2 p-3 font-mono text-[12px] text-gray-11">
          {body}
        </pre>
      </div>
    </div>
  );
}
