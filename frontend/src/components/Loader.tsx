type SpinnerProps = {
  size?: number;
  className?: string;
};

export function Spinner({ size = 16, className = "" }: SpinnerProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className={`animate-spin ${className}`}
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        fill="none"
        strokeDasharray="44"
        strokeDashoffset="22"
        opacity="0.85"
      />
    </svg>
  );
}

type LoadingTextProps = {
  text: string;
  className?: string;
};

export function LoadingText({ text, className = "" }: LoadingTextProps) {
  return (
    <span className={`inline-flex items-baseline ${className}`}>
      <span>{text}</span>
      <span aria-hidden="true" className="loading-dots ml-0.5 w-[1ch] inline-block" />
    </span>
  );
}
