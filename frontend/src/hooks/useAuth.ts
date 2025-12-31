import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useAuthStore } from '../stores/authStore';
import { healthApi } from '../lib/api';

export function useAuth() {
  const { setApiKey, logout } = useAuthStore();
  const [loginError, setLoginError] = useState(false);

  const loginMutation = useMutation({
    mutationFn: async (apiKey: string) => {
      // Temporarily set the API key to test it
      localStorage.setItem('apiKey', apiKey);
      try {
        // Validate by calling health endpoint
        const health = await healthApi.check();
        return { apiKey, health };
      } catch {
        localStorage.removeItem('apiKey');
        throw new Error('Invalid API key');
      }
    },
    onSuccess: ({ apiKey }) => {
      setApiKey(apiKey);
      setLoginError(false);
    },
    onError: () => {
      setLoginError(true);
    },
  });

  return {
    login: (apiKey: string) => loginMutation.mutate(apiKey),
    logout,
    isLoggingIn: loginMutation.isPending,
    loginError,
  };
}
