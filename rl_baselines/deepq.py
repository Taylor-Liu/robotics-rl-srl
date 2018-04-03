from baselines import deepq
from baselines import logger
from baselines.common.vec_env.vec_frame_stack import VecFrameStack
from baselines.common.vec_env import VecEnv

import environments.kuka_button_gym_env as kuka_env
from pytorch_agents.envs import make_env
from rl_baselines.utils import createTensorflowSession
from .utils import WrapVecNormalize

class CustomDummyVecEnv(VecEnv):
    """Dummy class in order to use FrameStack with DQN"""
    def __init__(self, env_fns):
        """
        :param env_fns: ([function])
        """
        assert len(env_fns) == 1, "This dummy class does not support multiprocessing"
        self.envs = [fn() for fn in env_fns]
        env = self.envs[0]
        VecEnv.__init__(self, len(env_fns), env.observation_space, env.action_space)
        self.env = self.envs[0]
        self.actions = None
        self.obs = None
        self.reward, self.done, self.infos = None, None, None

    def step_wait(self):
        self.obs, self.reward, self.done, self.infos = self.env.step(self.actions[0])
        return self.obs[None], self.reward, [self.done], [self.infos]

    def step_async(self, actions):
        """
        :param actions: ([int])
        """
        self.actions = actions

    def reset(self):
        return self.env.reset()

    def close(self):
        return


class WrapFrameStack(VecFrameStack):
    """
    Wrap VecFrameStack in order to be usable with dqn
    and scale output if necessary
    """

    def __init__(self, venv, nstack, normalize=True):
        super(WrapFrameStack, self).__init__(venv, nstack)
        self.factor = 255.0 if normalize else 1

    def step(self, action):
        self.step_async([action])
        stackedobs, rews, news, infos = self.step_wait()
        return stackedobs[0] / self.factor, rews, news[0], infos[0]

    def reset(self):
        """
        Reset all environments
        """
        stackedobs = super(WrapFrameStack, self).reset()
        return stackedobs[0] / self.factor


def customArguments(parser):
    """
    :param parser: (ArgumentParser Object)
    :return: (ArgumentParser Object)
    """
    parser.add_argument('--prioritized', type=int, default=1)
    parser.add_argument('--dueling', type=int, default=1)
    parser.add_argument('--buffer-size', type=int, default=int(1e3), help="Replay buffer size")
    return parser


def main(args, callback):
    """
    :param args: (argparse.Namespace Object)
    :param callback: (function)
    """
    logger.configure()

    env = CustomDummyVecEnv([make_env(args.env, args.seed, 0, args.log_dir, pytorch=False)])
    # Normalize only raw pixels
    normalize = args.srl_model == ""
    # WARNING: when using framestacking, the memory used by the replay buffer can grow quickly
    env = WrapFrameStack(env, args.num_stack, normalize=normalize)
    env =  WrapVecNormalize(env)
    
    createTensorflowSession()

    if args.srl_model != "":
        model = deepq.models.mlp([64, 64])
    else:
        # Atari CNN
        model = deepq.models.cnn_to_mlp(
            convs=[(32, 8, 4), (64, 4, 2), (64, 3, 1)],
            hiddens=[256],
            dueling=bool(args.dueling),
        )

    # TODO: tune params
    act = deepq.learn(
        env,
        q_func=model,
        lr=1e-4,
        max_timesteps=args.num_timesteps,
        buffer_size=args.buffer_size,
        exploration_fraction=0.1,
        exploration_final_eps=0.01,
        train_freq=4,
        learning_starts=500,
        target_network_update_freq=500,
        gamma=0.99,
        prioritized_replay=bool(args.prioritized),
        print_freq=10,  # Print every 10 episodes
        callback=callback
    )
    act.save(args.log_dir + "deepq_model_end.pkl")
    env.close()
