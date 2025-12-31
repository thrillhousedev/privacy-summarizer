import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

interface AuthState {
  apiKey: string | null;
  isAuthenticated: boolean;
  setApiKey: (apiKey: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      apiKey: null,
      isAuthenticated: false,
      setApiKey: (apiKey) => {
        localStorage.setItem('apiKey', apiKey);
        set({ apiKey, isAuthenticated: true });
      },
      logout: () => {
        localStorage.removeItem('apiKey');
        set({ apiKey: null, isAuthenticated: false });
      },
    }),
    {
      name: 'auth-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ apiKey: state.apiKey, isAuthenticated: state.isAuthenticated }),
    }
  )
);
