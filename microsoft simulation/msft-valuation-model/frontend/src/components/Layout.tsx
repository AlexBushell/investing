import type { PropsWithChildren, ReactNode } from "react";

type LayoutProps = PropsWithChildren<{
  header: ReactNode;
  sidebar: ReactNode;
  rightRail?: ReactNode;
}>;

export function Layout({ header, sidebar, rightRail, children }: LayoutProps) {
  return (
    <div className="app-shell">
      <header className="hero-panel">{header}</header>
      <aside className="sidebar-panel">{sidebar}</aside>
      <main className="main-panel">{children}</main>
      <aside className="rail-panel">{rightRail}</aside>
    </div>
  );
}
