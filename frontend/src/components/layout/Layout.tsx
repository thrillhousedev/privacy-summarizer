import type { ReactNode } from 'react';
import Sidebar from './Sidebar';
import Navbar from './Navbar';

interface LayoutProps {
  children: ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <Navbar />
      <div className="flex pt-14">
        <Sidebar />
        <main className="flex-1 p-6 lg:p-8 ml-64">
          {children}
        </main>
      </div>
    </div>
  );
}
