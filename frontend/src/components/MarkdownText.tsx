import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { FC } from "react";

interface MarkdownTextProps {
  text: string;
  fontScale?: number;
}

export const MarkdownText: FC<MarkdownTextProps> = ({ text, fontScale = 1 }) => {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => (
          <p className="mb-4">{children}</p>
        ),
        ul: ({ children }) => (
          <ul className="mb-4 pl-6 list-disc">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-4 pl-6 list-decimal">{children}</ol>
        ),
        li: ({ children }) => (
          <li className="mb-1">{children}</li>
        ),
        code: ({ children, className }) => {
          // Check if this code is inside a <pre> (i.e., it's a code block, not inline)
          const isInline = !className && typeof children === 'string' && !children.includes('\n');

          if (isInline) {
            return (
              <code
                className="px-1.5 py-0.5 bg-user-bubble rounded font-mono"
                style={{ fontSize: `${14 * fontScale}px` }}
              >
                {children}
              </code>
            );
          }

          // It's a code block (with or without language tag)
          return (
            <pre
              className="mb-4 p-4 bg-code-bg rounded-lg overflow-x-auto font-mono whitespace-pre"
              style={{ fontSize: `${14 * fontScale}px` }}
            >
              <code className={className}>{children}</code>
            </pre>
          );
        },
        pre: ({ children }) => <>{children}</>,
        blockquote: ({ children }) => (
          <blockquote className="mb-4 pl-4 border-l-4 border-primary italic text-muted">
            {children}
          </blockquote>
        ),
        h1: ({ children }) => (
          <h1
            className="mb-3 font-bold"
            style={{ fontSize: `${24 * fontScale}px` }}
          >
            {children}
          </h1>
        ),
        h2: ({ children }) => (
          <h2
            className="mb-2 font-bold"
            style={{ fontSize: `${20 * fontScale}px` }}
          >
            {children}
          </h2>
        ),
        h3: ({ children }) => (
          <h3
            className="mb-2 font-bold"
            style={{ fontSize: `${18 * fontScale}px` }}
          >
            {children}
          </h3>
        ),
        a: ({ href, children }) => (
          <a href={href} className="text-primary underline break-words">
            {children}
          </a>
        ),
        strong: ({ children }) => (
          <strong className="font-bold">{children}</strong>
        ),
        em: ({ children }) => (
          <em className="italic">{children}</em>
        ),
        table: ({ children }) => (
          <div className="mb-4 overflow-x-auto">
            <table className="min-w-full border-collapse">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="border-b border-muted">{children}</thead>
        ),
        tbody: ({ children }) => <tbody>{children}</tbody>,
        tr: ({ children }) => (
          <tr className="border-b border-muted/50">{children}</tr>
        ),
        th: ({ children }) => (
          <th className="px-3 py-2 text-left font-semibold">{children}</th>
        ),
        td: ({ children }) => (
          <td className="px-3 py-2">{children}</td>
        ),
      }}
    >
      {text}
    </Markdown>
  );
};
